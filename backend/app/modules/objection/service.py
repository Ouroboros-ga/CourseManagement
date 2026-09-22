"""异议域服务：本人异议创建、按范围读取、初核与终审（含终审更正考勤）。

事务与守卫约定（PERMISSIONS.md 13.2、技术方案 15，与 attendance/inspection 一致）：
- 写路径末尾**单次 commit**，失败抛 AppError 由依赖回滚；Repository 只 flush；
- 全局锁层级"考勤 → 异议"（技术方案 15）：创建先锁考勤记录行再在其保护下查重与写异议；
  终审先锁考勤再锁异议（populate_existing 重读），初核不改考勤故仅锁异议行；
- 事务内重读操作者有效权限纵深复核；审计 append-only 同事务写入。

数据范围与读取路径（PERMISSIONS.md 7.6、8）：
- 管理读取路径：持 objection.initial_review 或 objection.final_review（超管/教师；负责人经
  可选授予初核派生）→ 全学院异议可读；
- 本人读取路径：持 objection.read 且有有效 student_id（学生 / 绑定志愿者经角色并集继承）→
  仅 objection.student_id==本人；不可见与不存在统一 404 防枚举。

关键规则（技术方案 14）：
- 创建：学生仅对本人考勤、记录发起版本；同一考勤存在未完成异议（final_status=PENDING）→
  DUPLICATE_ACTIVE_OBJECTION；异议窗口超期（可配置）→ OBJECTION_WINDOW_CLOSED；证明材料须
  READY、本人上传、类别 OBJECTION_PROOF、未过期，关联前锁文件行与到期清理串行化；
- 初核：PENDING→PASSED/REJECTED，**不改考勤**，为终审提供参考；
- 终审：PENDING→APPROVED/REJECTED。通过且需更正时，同一事务改判考勤当前值、追加
  OBJECTION_FINAL 版本并审计；考勤版本≠发起时版本 → VERSION_CONFLICT，绝不覆盖他人新认定。
  更正需 objection.final_review AND attendance.correct。**报表源修订号统一留 P7 施加**。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.config import Settings, get_settings
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
)
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileCategory, FileStatus
from app.modules.file.repository import FileRepository
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.objection import permissions as perms
from app.modules.objection.models import (
    Objection,
    ObjectionFile,
    ObjectionFinalStatus,
    ObjectionInitialStatus,
)
from app.modules.objection.repository import ObjectionRepository
from app.modules.objection.schemas import (
    ObjectionCreateRequest,
    ObjectionFinalReviewRequest,
    ObjectionInitialReviewRequest,
    ObjectionResponse,
)


class ObjectionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ObjectionRepository(session)
        self._file_repo = FileRepository(session)
        self._identity = IdentityRepository(session)
        self._settings: Settings = get_settings()

    # ================================================================== #
    # 守卫 / 身份 / 审计
    # ================================================================== #
    def _lock_actor(self, actor_user_id: int) -> set[str]:
        """锁定操作者账号并重读有效权限（纵深复核，PERMISSIONS.md 13.2）。"""
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None:
            raise UnauthenticatedError("操作者账号不可用")
        return set(self._identity.list_effective_permissions(actor_user_id))

    def _require(self, actor_user_id: int, code: str) -> set[str]:
        permissions = self._lock_actor(actor_user_id)
        if code not in permissions:
            raise PermissionDeniedError()
        return permissions

    def _student_id(self, actor_user_id: int) -> int | None:
        acct = self._identity.get_user_by_id(actor_user_id)
        return acct.student_id if acct is not None else None

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_id: str,
        after: dict | None,
        reason: str | None,
        request_id: str | None,
        before: dict | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="objection",
                resource_id=resource_id,
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()

    # ================================================================== #
    # 创建（objection.create + SELF_STUDENT / OWN_OBJECTION）
    # ================================================================== #
    def create(
        self,
        actor: CurrentUser,
        attendance_record_id: int,
        body: ObjectionCreateRequest,
        request_id: str | None,
    ) -> ObjectionResponse:
        """学生对本人某条考勤提交异议（技术方案 14、15）。

        锁考勤行后校验归属 / 窗口 / 重复未完成异议，记录发起版本为 base_attendance_version，
        并锁验证明材料后同事务落库。并发下第二个创建者在同一考勤行锁上排队，看到既有未完成
        异议即得 DUPLICATE_ACTIVE_OBJECTION，保证"同一考勤只有一个进行中异议"。
        """
        self._require(actor.id, perms.OBJECTION_CREATE_PERMISSION)
        sid = self._student_id(actor.id)
        if sid is None:
            raise PermissionDeniedError("未绑定学生身份，无法对考勤提出异议")

        # 全局锁层级：先锁考勤记录行。
        record = self._repo.get_attendance_for_update(attendance_record_id)
        if record is None or record.student_id != sid:
            # 他人考勤与不存在统一 404，防枚举（PERMISSIONS.md 7.6）。
            raise NotFoundError("考勤记录不存在或不可提出异议")

        self._assert_within_window(record)
        if body.desired_type == record.effective_type:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "异议诉求类型与当前认定相同，无需提出",
                http_status=422,
                field_errors={"desired_type": body.desired_type},
            )
        if self._repo.has_open_objection(record.id):
            raise ConflictError(
                ErrorCode.DUPLICATE_ACTIVE_OBJECTION, "该考勤已有未完成的异议，请等待处理"
            )

        file_ids = self._validate_proof_files(actor.id, body.file_ids)

        obj = Objection(
            attendance_record_id=record.id,
            student_id=sid,
            base_attendance_version=record.current_version,
            reason=body.reason,
            desired_type=body.desired_type,
            initial_status=ObjectionInitialStatus.PENDING.value,
            final_status=ObjectionFinalStatus.PENDING.value,
        )
        self._repo.add(obj)
        self._repo.flush()  # 取 objection.id 供文件关联与审计 resource_id
        for fid in file_ids:
            self._repo.add(ObjectionFile(objection_id=obj.id, file_id=fid))
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="objection.create",
            resource_id=f"{obj.id}",
            after={
                "attendance_record_id": record.id,
                "student_id": sid,
                "base_attendance_version": obj.base_attendance_version,
                "desired_type": obj.desired_type,
                "file_count": len(file_ids),
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(obj)
        return self._assemble([obj])[0]

    def _assert_within_window(self, record: AttendanceRecord) -> None:
        days = self._settings.objection_window_days
        if days <= 0:
            return  # 0 = 不限窗口（部署未定异议期时的保守值）
        deadline = record.created_at + timedelta(days=days)
        if utcnow() > deadline:
            raise ConflictError(
                ErrorCode.OBJECTION_WINDOW_CLOSED,
                f"已超过异议窗口（{days} 天），不能再对该考勤提出异议",
            )

    def _validate_proof_files(self, actor_id: int, file_ids: list[int]) -> list[int]:
        """锁验并去重异议证明材料：均须 READY、本人上传、类别相符、未过期（技术方案 16.2/713）。

        用与到期清理相同的文件行锁协议：get_for_update 后核验仍为 READY——若清理已将置
        PURGE_PENDING，此处即拒绝，避免"校验后新增异议关联而误删"（技术方案 713）。
        """
        uniq = list(dict.fromkeys(file_ids))
        cap = self._settings.objection_max_files
        if cap and len(uniq) > cap:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"单次异议证明材料不得超过 {cap} 个",
                http_status=422,
                field_errors={"file_ids": uniq},
            )
        bad: list[int] = []
        now = utcnow()
        for fid in uniq:
            f = self._file_repo.get_for_update(fid)
            if (
                f is None
                or f.status != FileStatus.READY.value
                or f.category != FileCategory.OBJECTION_PROOF.value
                or f.uploader_user_id != actor_id
                or (f.expires_at is not None and f.expires_at <= now)
            ):
                bad.append(fid)
        if bad:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "材料不存在、未就绪、非本人上传、类别不符或已过期",
                http_status=422,
                field_errors={"file_ids": bad},
            )
        return uniq

    # ================================================================== #
    # 读取（管理范围 vs 本人 OWN_OBJECTION）
    # ================================================================== #
    def list_objections(
        self,
        actor: CurrentUser,
        params: PageParams,
        *,
        attendance_record_id: int | None,
        final_status: str | None,
        initial_status: str | None,
    ) -> dict:
        permissions = self._lock_actor(actor.id)
        scope, sid = self._read_scope(actor.id, permissions)
        rows, total = self._repo.list_objections(
            params,
            student_id=None if perms.is_manage_scope(scope) else sid,
            attendance_record_id=attendance_record_id,
            final_status=final_status,
            initial_status=initial_status,
        )
        return {
            "items": [d.model_dump() for d in self._assemble(rows)],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_objection(self, actor: CurrentUser, objection_id: int) -> ObjectionResponse:
        permissions = self._lock_actor(actor.id)
        scope, sid = self._read_scope(actor.id, permissions)
        obj = self._repo.get_objection(objection_id)
        if obj is None or not self._can_read(scope, sid, obj):
            raise NotFoundError("异议不存在或不可见")
        return self._assemble([obj])[0]

    def _read_scope(
        self, actor_user_id: int, permissions: set[str]
    ) -> tuple[perms.ObjectionScope, int | None]:
        scope = perms.resolve_read_scope(permissions)
        if perms.is_manage_scope(scope):
            return scope, None
        if scope is perms.ObjectionScope.OWN:
            sid = self._student_id(actor_user_id)
            if sid is None:
                # 持 objection.read 却无有效学生绑定：降级为无路径，不退化为全量查询。
                return perms.ObjectionScope.NONE, None
            return scope, sid
        return perms.ObjectionScope.NONE, None

    def _can_read(self, scope: perms.ObjectionScope, sid: int | None, obj: Objection) -> bool:
        if perms.is_manage_scope(scope):
            return True
        return sid is not None and sid == obj.student_id

    # ================================================================== #
    # 初核（objection.initial_review；不改考勤）
    # ================================================================== #
    def initial_review(
        self,
        actor: CurrentUser,
        objection_id: int,
        body: ObjectionInitialReviewRequest,
        request_id: str | None,
    ) -> ObjectionResponse:
        """初核：PENDING→PASSED/REJECTED，仅记录参考意见，绝不改考勤（技术方案 14）。

        不改考勤故不触及考勤锁层，仅锁异议行（全局层级对缺席层跳过）。
        """
        self._require(actor.id, perms.OBJECTION_INITIAL_REVIEW_PERMISSION)
        obj = self._repo.get_objection_for_update(objection_id)
        if obj is None:
            raise NotFoundError("异议不存在")
        if obj.initial_status != ObjectionInitialStatus.PENDING.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该异议已完成初核")
        prev = obj.initial_status
        obj.initial_status = body.decision
        obj.initial_reviewed_by = actor.id
        obj.initial_reviewed_at = utcnow()
        obj.initial_comment = body.comment
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="objection.initial_review",
            resource_id=f"{obj.id}",
            before={"initial_status": prev},
            after={
                "initial_status": obj.initial_status,
                "initial_reviewed_by": actor.id,
            },
            reason=body.comment,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(obj)
        return self._assemble([obj])[0]

    # ================================================================== #
    # 终审（objection.final_review；通过且需更正时同事务改判考勤）
    # ================================================================== #
    def final_review(
        self,
        actor: CurrentUser,
        objection_id: int,
        body: ObjectionFinalReviewRequest,
        request_id: str | None,
    ) -> ObjectionResponse:
        """终审：PENDING→APPROVED/REJECTED（技术方案 14、15；PERMISSIONS.md 758）。

        通过并给出与当前认定不同的 final_type 即"更正"，须 objection.final_review AND
        attendance.correct；更正前校验考勤当前版本 == 异议发起版本，否则 VERSION_CONFLICT，
        不覆盖他人新认定。锁序：先锁考勤、再锁异议（populate_existing 重读状态）。驳回不改考勤。
        """
        permissions = self._require(actor.id, perms.OBJECTION_FINAL_REVIEW_PERMISSION)

        anchor = self._repo.get_objection(objection_id)
        if anchor is None:
            raise NotFoundError("异议不存在")

        # 全局锁层级：先锁考勤行，再锁异议行并重读状态。
        record = self._repo.get_attendance_for_update(anchor.attendance_record_id)
        obj = self._repo.get_objection_for_update(objection_id)
        if record is None or obj is None:
            raise NotFoundError("异议不存在")
        if obj.final_status != ObjectionFinalStatus.PENDING.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该异议已完成终审")

        now = utcnow()
        if body.decision == "REJECTED":
            obj.final_status = ObjectionFinalStatus.REJECTED.value
            obj.final_reviewed_by = actor.id
            obj.final_reviewed_at = now
            obj.final_comment = body.comment
            self._repo.flush()
            self._audit(
                actor_user_id=actor.id,
                action="objection.final_review",
                resource_id=f"{obj.id}",
                before={"final_status": ObjectionFinalStatus.PENDING.value},
                after={"final_status": obj.final_status, "corrected": False},
                reason=body.comment,
                request_id=request_id,
            )
            self._session.commit()
            self._session.refresh(obj)
            return self._assemble([obj])[0]

        # APPROVED：须给出终审判定类型。
        if body.final_type is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "终审通过须给出判定类型 final_type",
                http_status=422,
                field_errors={"final_type": None},
            )
        target = body.final_type
        needs_correction = target != record.effective_type
        attendance_before = {
            "effective_type": record.effective_type,
            "current_version": record.current_version,
        }
        if needs_correction:
            if perms.ATTENDANCE_CORRECT_PERMISSION not in permissions:
                raise PermissionDeniedError("终审更正考勤需同时具备 attendance.correct")
            # 审阅者所见版本须与考勤当前一致（乐观锁），且不覆盖他人在异议发起后的新认定。
            if body.current_version != record.current_version:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT, "考勤已被他人更正，请刷新后重看再操作"
                )
            if record.current_version != obj.base_attendance_version:
                raise ConflictError(
                    ErrorCode.VERSION_CONFLICT,
                    "考勤版本已与发起异议时不同，请重新查看后处理，不覆盖他人新认定",
                )
            record.effective_type = target
            record.current_version = obj.base_attendance_version + 1
            self._repo.flush()
            self._repo.add(
                AttendanceRecordVersion(
                    attendance_record_id=record.id,
                    version_no=record.current_version,
                    attendance_type=target,
                    source_type=AttendanceSourceType.OBJECTION_FINAL.value,
                    source_id=obj.id,
                    changed_by=actor.id,
                    reason=body.comment or obj.reason,
                )
            )
        self._repo.flush()
        obj.final_status = ObjectionFinalStatus.APPROVED.value
        obj.final_reviewed_by = actor.id
        obj.final_reviewed_at = now
        obj.final_comment = body.comment
        obj.final_attendance_type = target
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="objection.final_review",
            resource_id=f"{obj.id}",
            before={
                "final_status": ObjectionFinalStatus.PENDING.value,
                "attendance": attendance_before,
            },
            after={
                "final_status": obj.final_status,
                "final_attendance_type": target,
                "corrected": needs_correction,
                "attendance": {
                    "effective_type": record.effective_type,
                    "current_version": record.current_version,
                },
            },
            reason=body.comment,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(obj)
        # 说明：报表源修订号（report_source_revision）对考勤类变更的统一递增留待 P7 报表域
        # 一次性施加（更正 / 终审改判等所有影响考勤的路径同批接入），此处不单独造数。
        return self._assemble([obj])[0]

    # ================================================================== #
    # 装配（批量取材料关联，禁 N+1）
    # ================================================================== #
    def _assemble(self, objs: Sequence[Objection]) -> list[ObjectionResponse]:
        if not objs:
            return []
        file_map = self._repo.map_file_ids_by_objection([o.id for o in objs])
        out: list[ObjectionResponse] = []
        for o in objs:
            out.append(
                ObjectionResponse(
                    id=o.id,
                    attendance_record_id=o.attendance_record_id,
                    student_id=o.student_id,
                    base_attendance_version=o.base_attendance_version,
                    reason=o.reason,
                    desired_type=o.desired_type,
                    initial_status=o.initial_status,
                    initial_reviewed_by=o.initial_reviewed_by,
                    initial_reviewed_at=o.initial_reviewed_at,
                    initial_comment=o.initial_comment,
                    final_status=o.final_status,
                    final_reviewed_by=o.final_reviewed_by,
                    final_reviewed_at=o.final_reviewed_at,
                    final_comment=o.final_comment,
                    final_attendance_type=o.final_attendance_type,
                    file_ids=file_map.get(o.id, []),
                    created_at=o.created_at,
                    updated_at=o.updated_at,
                )
            )
        return out


__all__ = ["ObjectionService"]
