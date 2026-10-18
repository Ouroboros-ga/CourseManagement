"""教职工档案与任职关系的学院写服务：范围、版本、重叠与审计同事务完成。

范围只来自服务端会话与显式学院工作区；请求体不携带学校/学院所有权字段，也不按
姓名匹配账号或档案。所有入口统一按学院—账号—档案—稳定父资源—关系的顺序加锁
（学院由范围解析先行锁定），关系为空时仍锁父行；跨行重叠由服务判定，
数据库 CHECK 只兜住单行约束。
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.database import iso_utc
from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.academic.staff_repository import StaffRepository
from app.modules.academic.staff_rules import classify_teaching_overlap, handover_start_allowed
from app.modules.academic.staff_schemas import (
    AccountLink,
    AccountUnlink,
    RelationEnd,
    ResponsibilityCreate,
    ResponsibilityHandover,
    StaffCreate,
    StaffUpdate,
    TeachingAssignmentCreate,
)
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.authorization import STAFF_MANAGE_ACTION
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.organization.models import College
from app.modules.organization.service import atomic_write, validated

ACTION = STAFF_MANAGE_ACTION


class StaffManagementService:
    def __init__(
        self, db: Session, actor: CurrentUser, college_id: int, request_id: str | None = None
    ) -> None:
        self.db = db
        self.actor = actor
        self.college_id = college_id
        self.request_id = request_id
        self.repo = StaffRepository(db)
        self.identity = IdentityRepository(db)

    # ------------------------------------------------------------------ #
    # 范围与投影
    # ------------------------------------------------------------------ #
    def _authorize(self, *, write: bool) -> None:
        """逐操作复核学院范围；写操作同时锁定并校验学院有效。"""
        resolve_scope(self.db, self.actor, self.college_id, ACTION, write=write)

    def _college(self) -> College:
        return self.repo.college(self.college_id)

    def _dto(self, row: Any) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for column in row.__table__.columns:
            value = getattr(row, column.name)
            if value is None:
                data[column.name] = None
            elif column.name == "id" or column.foreign_keys:
                data[column.name] = str(value)
            elif isinstance(value, datetime):
                data[column.name] = iso_utc(value)
            elif hasattr(value, "isoformat"):
                data[column.name] = value.isoformat()
            else:
                data[column.name] = value
        return data

    def _audit(
        self,
        action: str,
        row: Any,
        before: dict[str, Any] | None,
        reason: str | None,
        *,
        after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = after if after is not None else self._dto(row)
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action=action,
                resource_type=row.__tablename__,
                resource_id=str(row.id),
                before_json=scoped_snapshot(before, self.college_id),
                after_json=scoped_snapshot(payload, self.college_id),
                reason=reason,
                request_id=self.request_id,
            )
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            raise ConflictError(message="工号重复或任职关系已变化，未保存") from exc
        return payload

    def _version(self, row: Any, expected: int, label: str) -> None:
        if row.lock_version != expected:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, f"{label}已变化，请刷新后重试")

    def _flush(self) -> None:
        """并发下预检查可能漏网，由约束冲突映射为 409 而不是 500。"""
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message="工号重复或任职关系已变化，未保存") from exc

    # ------------------------------------------------------------------ #
    # 档案
    # ------------------------------------------------------------------ #
    def list_staff(
        self, params: PageParams, *, keyword: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        self._authorize(write=False)
        rows, total = self.repo.page_profiles(
            self.college_id, params, keyword=keyword, status=status
        )
        return {
            "items": [self._dto(row) for row in rows],
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    def get_staff(self, staff_id: int) -> dict[str, Any]:
        self._authorize(write=False)
        return self._dto(self.repo.profile(self.college_id, staff_id))

    @atomic_write
    def create_staff(self, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(StaffCreate, data)
        college = self._college()
        if self.repo.staff_no_in_school(college.school_id, body.staff_no) is not None:
            raise ConflictError(message="工号在本学校内已存在")
        row = FacultyStaff(
            school_id=college.school_id,
            college_id=self.college_id,
            staff_no=body.staff_no,
            name=body.name,
            phone=body.phone,
            status=body.status,
        )
        self.db.add(row)
        self._flush()
        return self._audit("staff.create", row, None, body.reason)

    @atomic_write
    def update_staff(self, staff_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(StaffUpdate, data)
        row = self.repo.profile(self.college_id, staff_id, lock=True)
        self._version(row, body.lock_version, "档案")
        before = self._dto(row)
        for key, value in body.model_dump(
            exclude_unset=True, exclude={"lock_version", "reason"}
        ).items():
            setattr(row, key, value)
        row.lock_version += 1
        self._flush()
        return self._audit("staff.update", row, before, body.reason)

    @atomic_write
    def link_account(self, staff_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """明确关联既有账号；账号身份、角色和权限都不在此变更。"""
        self._authorize(write=True)
        body = validated(AccountLink, data)
        account = self.identity.get_user_by_id_for_update(int(body.user_id))
        if account is None or account.status != "ACTIVE":
            raise NotFoundError("账号不存在或已停用")
        row = self.repo.profile(self.college_id, staff_id, lock=True)
        self._version(row, body.lock_version, "档案")
        if row.user_id == account.id:
            return self._dto(row)
        if row.user_id is not None:
            raise ConflictError(message="档案已关联其他账号，请先解绑")
        if self.repo.profile_bound_to_account(account.id) is not None:
            raise ConflictError(message="该账号已关联其他教职工档案")
        before = self._dto(row)
        row.user_id = account.id
        row.lock_version += 1
        self._flush()
        return self._audit("staff.account_link", row, before, body.reason)

    @atomic_write
    def unlink_account(self, staff_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """解绑即由下一次请求重新判定，不撤销账号的其他身份会话。"""
        self._authorize(write=True)
        body = validated(AccountUnlink, data)
        row = self.repo.profile(self.college_id, staff_id, lock=True)
        self._version(row, body.lock_version, "档案")
        if row.user_id is None:
            return self._dto(row)
        before = self._dto(row)
        row.user_id = None
        row.lock_version += 1
        self._flush()
        return self._audit("staff.account_unlink", row, before, body.reason)

    # ------------------------------------------------------------------ #
    # 授课关系
    # ------------------------------------------------------------------ #
    def list_teaching_assignments(
        self, *, staff_id: int | None = None, teaching_class_id: int | None = None
    ) -> list[dict[str, Any]]:
        self._authorize(write=False)
        rows = self.repo.list_teaching(
            self.college_id, staff_id=staff_id, teaching_class_id=teaching_class_id
        )
        names = {
            staff.id: staff for staff in self.db.scalars(
                select(FacultyStaff).where(FacultyStaff.id.in_({r.staff_id for r in rows}))
            )
        }
        return [
            {**self._dto(row), "staff_no": names[row.staff_id].staff_no,
             "staff_name": names[row.staff_id].name}
            for row in rows
        ]

    def _reject_teaching_overlap(
        self,
        *,
        staff_id: int,
        semester_id: int,
        anchor_type: str,
        teaching_class_id: int | None,
        academic_offering_id: str | None,
        covered_offering_id: str | None,
        start: date,
        end: date | None,
        exclude_id: int | None = None,
    ) -> None:
        """同锚点重复、以及 LOCAL 与 SHARED 覆盖同一资源的重叠都在写入时拒绝。

        判定本身在 `academic.staff_rules`，与资料导入共用一套口径；`covered_offering_id`
        是本次任命实际触达的共享身份。
        """
        overlap = classify_teaching_overlap(
            self.repo.overlapping_teaching(
                staff_id, semester_id, start, end, exclude_id=exclude_id
            ),
            anchor_type=anchor_type,
            teaching_class_id=teaching_class_id,
            academic_offering_id=academic_offering_id,
            covered_offering_id=covered_offering_id,
            exclude_id=exclude_id,
        )
        if overlap.same_anchor is not None or overlap.conflicts:
            raise ConflictError(message="同一课程在有效期内已有重叠任命")

    @atomic_write
    def create_teaching_assignment(self, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(TeachingAssignmentCreate, data)
        college = self._college()
        staff = self.repo.profile(self.college_id, int(body.staff_id), lock=True)
        if staff.status != "ACTIVE":
            raise ConflictError(message="档案已停用，不能建立授课任命")
        semester = self.repo.semester(int(body.semester_id))
        teaching_class_id: int | None = None
        academic_offering_id: str | None = None
        covered_offering_id: str | None = None
        if body.anchor_type == "LOCAL":
            target = self.repo.teaching_class(self.college_id, int(body.teaching_class_id))
            if target.semester_id != semester.id:
                raise AppError(ErrorCode.VALIDATION_ERROR, "教学班不属于该学期", 422)
            teaching_class_id = target.id
            covered_offering_id = target.academic_offering_id
        else:
            offering = self.repo.offering(college.school_id, body.academic_offering_id or "")
            if offering.semester_id != semester.id:
                raise AppError(ErrorCode.VALIDATION_ERROR, "共享课程身份与学期不一致", 422)
            academic_offering_id = offering.id
            covered_offering_id = offering.id
        self._reject_teaching_overlap(
            staff_id=staff.id,
            semester_id=semester.id,
            anchor_type=body.anchor_type,
            teaching_class_id=teaching_class_id,
            academic_offering_id=academic_offering_id,
            covered_offering_id=covered_offering_id,
            start=body.effective_from,
            end=body.effective_to,
        )
        row = TeachingStaffAssignment(
            staff_id=staff.id,
            semester_id=semester.id,
            anchor_type=body.anchor_type,
            teaching_class_id=teaching_class_id,
            academic_offering_id=academic_offering_id,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
        )
        self.db.add(row)
        self._flush()
        return self._audit("teaching_assignment.create", row, None, body.reason)

    @atomic_write
    def end_teaching_assignment(self, relation_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(RelationEnd, data)
        row = self.repo.relation(TeachingStaffAssignment, self.college_id, relation_id)
        return self._end_relation(TeachingStaffAssignment, row, body, "teaching_assignment.end")

    # ------------------------------------------------------------------ #
    # 班级责任关系
    # ------------------------------------------------------------------ #
    def list_responsibilities(
        self,
        *,
        staff_id: int | None = None,
        administrative_class_id: int | None = None,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        self._authorize(write=False)
        rows = self.repo.list_responsibilities(
            self.college_id,
            staff_id=staff_id,
            administrative_class_id=administrative_class_id,
            as_of=as_of,
        )
        return [self._dto(row) for row in rows]

    @atomic_write
    def create_responsibility(self, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(ResponsibilityCreate, data)
        staff = self.repo.profile(self.college_id, int(body.staff_id), lock=True)
        if staff.status != "ACTIVE":
            raise ConflictError(message="档案已停用，不能建立责任任命")
        # 责任关系只落在档案所属学院的行政班，与只读谓词的学院交集保持一致。
        admin_class = self.repo.administrative_class(
            staff.college_id, int(body.administrative_class_id)
        )
        if self.repo.overlapping_responsibilities(
            admin_class.id, body.duty, body.effective_from, body.effective_to
        ):
            raise ConflictError(message="同班同职责已有在职任命")
        row = ClassStaffResponsibility(
            staff_id=staff.id,
            administrative_class_id=admin_class.id,
            duty=body.duty,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
        )
        self.db.add(row)
        self._flush()
        return self._audit("responsibility.create", row, None, body.reason)

    @atomic_write
    def end_responsibility(self, relation_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._authorize(write=True)
        body = validated(RelationEnd, data)
        row = self.repo.relation(ClassStaffResponsibility, self.college_id, relation_id)
        return self._end_relation(ClassStaffResponsibility, row, body, "responsibility.end")

    @atomic_write
    def handover_responsibility(self, relation_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """一个事务内结束旧关系并建立新关系；交接日即新关系开始日。"""
        self._authorize(write=True)
        body = validated(ResponsibilityHandover, data)
        row = self.repo.relation(ClassStaffResponsibility, self.college_id, relation_id)
        self._version(row, body.lock_version, "任命")
        admin_class = self.repo.administrative_class(self.college_id, row.administrative_class_id)
        successor = self.repo.profile(self.college_id, int(body.successor_staff_id), lock=True)
        if successor.status != "ACTIVE":
            raise ConflictError(message="接班人档案已停用")
        if successor.id == row.staff_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "接班人与离任者相同", 422)
        if not handover_start_allowed(row.effective_from, body.effective_on):
            raise AppError(ErrorCode.VALIDATION_ERROR, "交接日必须晚于当前任命开始日", 422)
        if row.effective_to is not None and body.effective_on > row.effective_to:
            raise ConflictError(message="当前任命已结束，请先核对任职区间")
        if self.repo.overlapping_responsibilities(
            admin_class.id, row.duty, body.effective_on, None, exclude_id=row.id
        ):
            raise ConflictError(message="该班该职责已有其他在职任命")

        before = self._dto(row)
        row.effective_to = body.effective_on
        row.lock_version += 1
        created = ClassStaffResponsibility(
            staff_id=successor.id,
            administrative_class_id=admin_class.id,
            duty=row.duty,
            effective_from=body.effective_on,
        )
        self.db.add(created)
        self._flush()
        after = {
            "ended": self._dto(row),
            "created": self._dto(created),
            "successor_staff_no": successor.staff_no,
        }
        payload = self._audit(
            "responsibility.handover", row, before, body.reason, after=after
        )
        return {"ended": payload["ended"], "created": payload["created"]}

    # ------------------------------------------------------------------ #
    def _end_relation(self, model, row, body: RelationEnd, action: str) -> dict[str, Any]:
        self._version(row, body.lock_version, "任命")
        if body.effective_to <= row.effective_from:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束日必须晚于开始日", 422)
        # 先锁稳定父资源：责任关系锁行政班，授课关系锁档案（同一人重叠的串行点）。
        if model is ClassStaffResponsibility:
            self.repo.lock_administrative_class(row.administrative_class_id)
        else:
            self.repo.lock_profile(row.staff_id)
        extending = row.effective_to is None or body.effective_to > row.effective_to
        before = self._dto(row)
        row.effective_to = body.effective_to
        if extending:
            # 延长任职区间同样不得制造重叠任命。
            self._reject_extension_overlap(model, row)
        row.lock_version += 1
        self._flush()
        return self._audit(action, row, before, body.reason)

    def _reject_extension_overlap(self, model, row) -> None:
        if model is ClassStaffResponsibility:
            if self.repo.overlapping_responsibilities(
                row.administrative_class_id,
                row.duty,
                row.effective_from,
                row.effective_to,
                exclude_id=row.id,
            ):
                raise ConflictError(message="同班同职责已有在职任命")
            return
        teaching = row
        self._reject_teaching_overlap(
            staff_id=teaching.staff_id,
            semester_id=teaching.semester_id,
            anchor_type=teaching.anchor_type,
            teaching_class_id=teaching.teaching_class_id,
            academic_offering_id=teaching.academic_offering_id,
            covered_offering_id=teaching.academic_offering_id
            or self.repo.class_offering(teaching.teaching_class_id),
            start=teaching.effective_from,
            end=teaching.effective_to,
            exclude_id=teaching.id,
        )
