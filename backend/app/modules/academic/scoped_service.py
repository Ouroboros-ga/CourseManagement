"""基础数据院级入口；迁移期间与旧全局 Service 分离，逐项接入而非隐式放行。"""

from pydantic import Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
)
from app.modules.academic.models import AdministrativeClass
from app.modules.academic.schemas import (
    AdministrativeClassCreateRequest,
    AdministrativeClassUpdateRequest,
)
from app.modules.academic.scoped_repository import ScopedAcademicRepository
from app.modules.audit.models import AuditLog
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import CampusService, atomic_write, validated

READ_ACTIONS = {"students": "student.read", "qualifications": "volunteer.read"}


class ScopedClassCreate(AdministrativeClassCreateRequest):
    model_config = StrictModel.model_config


class ScopedClassUpdate(AdministrativeClassUpdateRequest):
    model_config = StrictModel.model_config
    ownership_version: int = Field(ge=1)

    @model_validator(mode="after")
    def non_nullable_fields(self):
        if any(
            key in self.model_fields_set and getattr(self, key) is None
            for key in ("class_name", "status")
        ):
            raise ValueError("名称和状态不能为 null")
        return self


class ScopedAcademicService:
    def __init__(
        self, db: Session, actor: CurrentUser, college_id: int, request_id: str | None = None
    ):
        self.db = db
        self.actor = actor
        self.college_id = college_id
        self.request_id = request_id
        self.campus = CampusService(db, request_id)

    def _repo(self, action: str, *, write=False):
        scope = resolve_scope(self.db, self.actor, self.college_id, action, write=write)
        return ScopedAcademicRepository(self.db, scope)

    def _dto(self, row):
        result = self.campus._dto(row)
        if row.__tablename__ == "course_schedule":
            # 不触发被禁止的关系隐式加载；子行只能经已授权父行查询。
            from sqlalchemy import select

            from app.modules.academic.models import CourseScheduleWeek

            result["week_nos"] = list(
                self.db.scalars(
                    select(CourseScheduleWeek.week_no)
                    .where(CourseScheduleWeek.schedule_id == row.id)
                    .order_by(CourseScheduleWeek.week_no)
                )
            )
        return result

    def list_rows(self, kind: str, params: PageParams, **filters):
        rows, total = self._repo(READ_ACTIONS.get(kind, "academic.read")).page(
            kind, params, **filters
        )
        return {
            "items": [self._dto(row) for row in rows],
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    def get_row(self, kind: str, rid: int):
        return self._dto(self._repo(READ_ACTIONS.get(kind, "academic.read")).get(kind, rid))

    def list_roster(self, teaching_class_id: int):
        return [self._dto(row) for row in self._repo("student.read").roster(teaching_class_id)]

    def _audit(self, action, row, before, reason=None, *, after_extra=None):
        after = self._dto(row)
        if after_extra:
            after.update(after_extra)
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action=action,
                resource_type=row.__tablename__,
                resource_id=str(row.id),
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=self.request_id,
            )
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            raise ConflictError(message="编码重复或关联已变化，未保存") from exc
        return after

    def _class_college_text(self, text):
        college = self.campus.repo.college(self.college_id)
        if text is not None and text != college.name:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "所属学院由工作区确定，不能通过文本修改", 422
            )
        return college.name

    @atomic_write
    def create_admin_class(self, data):
        self._repo("academic.manage", write=True)
        body = validated(ScopedClassCreate, data)
        row = AdministrativeClass(
            **body.model_dump(exclude={"reason", "college"}),
            college=self._class_college_text(body.college),
            college_id=self.college_id,
        )
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(message="编码重复，未保存") from exc
        return self._audit("academic.admin_class.create", row, None, body.reason)

    @atomic_write
    def update_admin_class(self, rid: int, data):
        repo = self._repo("academic.manage", write=True)
        body = validated(ScopedClassUpdate, data)
        row = repo.get("administrative_classes", rid, lock=True)
        if row.ownership_version != body.ownership_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "班级已变化，请刷新")
        if body.status is not None and body.status not in {"ACTIVE", "DISABLED"}:
            raise AppError(ErrorCode.VALIDATION_ERROR, "班级状态无效", 422)
        before = self._dto(row)
        if body.college is not None:
            self._class_college_text(body.college)
        for key, value in body.model_dump(
            exclude_unset=True, exclude={"reason", "college", "ownership_version"}
        ).items():
            setattr(row, key, value)
        row.ownership_version += 1
        self.db.flush()
        return self._audit("academic.admin_class.update", row, before, body.reason)

    @atomic_write
    def replace_roster(
        self,
        teaching_class_id: int,
        student_ids: list[str],
        ownership_version: int,
        reason: str | None = None,
    ):
        repo = self._repo("student.manage", write=True)
        teaching = repo.get("teaching_classes", teaching_class_id, lock=True)
        if repo.get("semesters", teaching.semester_id).status != "ACTIVE":
            raise ConflictError(message="学期已归档，不能替换名单")
        if teaching.ownership_version != ownership_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "教学班名单已变化，请刷新")
        try:
            ids = [int(value) for value in student_ids]
            if any(
                str(value) != raw or not 0 < value < 2**63
                for value, raw in zip(ids, student_ids, strict=True)
            ):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学生标识格式无效", 422) from exc
        if len(ids) > 5000:
            raise AppError(ErrorCode.VALIDATION_ERROR, "单批名单最多 5000 人", 422)
        if {row.id for row in repo.students(ids)} != set(ids):
            raise NotFoundError()
        # 对现有外院名单亦拒绝，不能借替换悄悄擦除历史混合名单。
        previous_students = repo.roster(teaching_class_id)
        before = self._dto(teaching)
        before["roster_student_ids"] = [str(row.id) for row in previous_students]
        repo.replace_roster(teaching_class_id, ids)
        teaching.ownership_version += 1
        self.db.flush()
        self._audit(
            "academic.roster.replace",
            teaching,
            before,
            reason,
            after_extra={"roster_student_ids": [str(sid) for sid in sorted(set(ids))]},
        )
        return [self._dto(row) for row in repo.roster(teaching_class_id)]
