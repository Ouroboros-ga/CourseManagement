"""考勤域服务：当前考勤与历史认定读取（按数据范围）、最终考勤更正（追加版本）。

事务与守卫约定（与 inspection/importer 一致，PERMISSIONS.md 13.2）：
- 写路径末尾**单次 commit**，失败抛 AppError 由依赖回滚；
- 更正为唯一写路径：锁考勤记录行 FOR UPDATE，事务内以客户端所见 current_version 做
  条件校验，不符即 409 VERSION_CONFLICT，绝不覆盖他人新认定（技术方案 15）；
- 事务内重读操作者有效权限纵深复核；审计 append-only 同事务写入。

数据范围（PERMISSIONS.md 7、技术方案 14）：
- GET /attendance（管理范围）：仅管理类角色可用，志愿者/学生越权读他人被拒 403；
- GET /me/attendance（SELF_STUDENT）：强制限定本人 student_id，未绑定直接拒绝；
- GET /attendance/{id} 与其 /versions：管理全量，非管理仅本人记录，否则统一 404 防枚举。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.attendance import permissions as perms
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
)
from app.modules.attendance.repository import AttendanceRepository
from app.modules.attendance.schemas import (
    AttendanceCorrectionRequest,
    AttendanceObjectionBrief,
    AttendanceResponse,
    AttendanceTaskBrief,
    AttendanceVersionResponse,
)
from app.modules.audit.models import AuditLog
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from app.modules.objection.models import Objection
from app.modules.report.source_revision import SourceRevisionService


class AttendanceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = AttendanceRepository(session)
        self._identity = IdentityRepository(session)

    # ================================================================== #
    # 守卫 / 审计 / 身份与范围
    # ================================================================== #
    def _require(self, actor_user_id: int, code: str) -> None:
        """事务内锁定操作者并重读有效权限纵深复核（PERMISSIONS.md 13.2）。"""
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor_user_id)):
            raise PermissionDeniedError()

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_type: str,
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
                resource_type=resource_type,
                resource_id=resource_id,
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()

    def _student_id(self, actor_user_id: int) -> int | None:
        acct = self._identity.get_user_by_id(actor_user_id)
        return acct.student_id if acct is not None else None

    # ================================================================== #
    # 读取
    # ================================================================== #
    def list_attendance(
        self,
        actor: CurrentUser,
        params: PageParams,
        *,
        task_id: int | None,
        semester_id: int | None,
        effective_type: str | None,
    ) -> dict:
        """管理范围考勤列表（GET /attendance）：仅管理类角色，越权 403。"""
        self._require(actor.id, perms.ATTENDANCE_READ_PERMISSION)
        if not perms.is_manage_scope(perms.resolve_read_scope(actor.roles)):
            raise PermissionDeniedError("仅管理角色可查看全量考勤，请用本人考勤入口")
        rows, total = self._repo.list_records(
            params,
            student_id=None,  # 管理范围：不加学生谓词
            task_id=task_id,
            semester_id=semester_id,
            effective_type=effective_type,
        )
        dto = self._assemble(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def list_my_attendance(
        self,
        actor: CurrentUser,
        params: PageParams,
        *,
        task_id: int | None,
        effective_type: str | None,
    ) -> dict:
        """本人考勤（GET /me/attendance，SELF_STUDENT）：强制 student_id=本人，未绑拒绝。"""
        self._require(actor.id, perms.ATTENDANCE_READ_PERMISSION)
        sid = self._student_id(actor.id)
        if sid is None:
            raise PermissionDeniedError("未绑定学生身份，无本人考勤")
        rows, total = self._repo.list_records(
            params, student_id=sid, task_id=task_id, effective_type=effective_type
        )
        dto = self._assemble(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_attendance(self, actor: CurrentUser, record_id: int) -> AttendanceResponse:
        self._require(actor.id, perms.ATTENDANCE_READ_PERMISSION)
        record = self._repo.get_record(record_id)
        if record is None or not self._can_read(actor, record):
            # 不可见与不存在统一 404，防枚举他人考勤（PERMISSIONS.md 7）。
            raise NotFoundError("考勤记录不存在或不可见")
        return self._assemble([record])[0]

    def list_versions(
        self, actor: CurrentUser, record_id: int
    ) -> list[AttendanceVersionResponse]:
        self._require(actor.id, perms.ATTENDANCE_READ_PERMISSION)
        record = self._repo.get_record(record_id)
        if record is None or not self._can_read(actor, record):
            raise NotFoundError("考勤记录不存在或不可见")
        return [
            AttendanceVersionResponse(
                id=v.id,
                attendance_record_id=v.attendance_record_id,
                version_no=v.version_no,
                attendance_type=v.attendance_type,
                source_type=v.source_type,
                source_id=v.source_id,
                changed_by=v.changed_by,
                reason=v.reason,
                created_at=v.created_at,
            )
            for v in self._repo.list_versions(record_id)
        ]

    def _can_read(self, actor: CurrentUser, record: AttendanceRecord) -> bool:
        """管理范围可读任意记录；否则仅本人 student_id 命中可读。"""
        if perms.is_manage_scope(perms.resolve_read_scope(actor.roles)):
            return True
        sid = self._student_id(actor.id)
        return sid is not None and sid == record.student_id

    # ================================================================== #
    # 更正（attendance.correct，仅超管/教师）
    # ================================================================== #
    def correct(
        self,
        actor: CurrentUser,
        record_id: int,
        body: AttendanceCorrectionRequest,
        request_id: str | None,
    ) -> AttendanceResponse:
        """更正最终考勤：改当前认定并追加版本，不重写原提交与既往版本（技术方案 14）。

        锁记录行 FOR UPDATE 后以客户端所见 current_version 条件校验；不符即 409，绝不覆盖
        他人新认定。更正不删除历史，仅新增一条 CORRECTION 来源版本（version_no 递增）。
        """
        self._require(actor.id, perms.ATTENDANCE_CORRECT_PERMISSION)
        record = self._repo.get_record_for_update(record_id)
        if record is None:
            raise NotFoundError("考勤记录不存在")
        if record.current_version != body.current_version:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "考勤已被他人更正，请刷新后重看再操作"
            )
        prev_type = record.effective_type
        prev_version = record.current_version
        record.effective_type = body.attendance_type
        record.current_version = prev_version + 1
        self._repo.flush()
        self._repo.add(
            AttendanceRecordVersion(
                attendance_record_id=record.id,
                version_no=record.current_version,
                attendance_type=body.attendance_type,
                source_type=AttendanceSourceType.CORRECTION.value,
                source_id=record.id,
                changed_by=actor.id,
                reason=body.reason,
            )
        )
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="attendance.correct",
            resource_type="attendance_record",
            resource_id=f"{record.id}",
            before={
                "effective_type": prev_type,
                "current_version": prev_version,
            },
            after={
                "effective_type": record.effective_type,
                "current_version": record.current_version,
            },
            reason=body.reason,
            request_id=request_id,
        )
        # 考勤事实被更正 → 同事务递增所属任务(学期,周)报表源修订号（技术方案 9.4；W7b 还 P6 挂账）。
        SourceRevisionService.bump_for_task_id(self._session, record.task_id)
        self._session.commit()
        return self._assemble([record])[0]

    # ================================================================== #
    # 装配（批量取任务上下文 + 名单快照，禁 N+1）
    # ================================================================== #
    def _assemble(
        self, records: Sequence[AttendanceRecord]
    ) -> list[AttendanceResponse]:
        if not records:
            return []
        task_ids = list({r.task_id for r in records})
        tasks = self._repo.map_tasks_by_ids(task_ids)
        version_by_task = {tid: t.roster_version for tid, t in tasks.items()}
        pairs = [(r.task_id, r.student_id) for r in records]
        display = self._repo.map_roster_display(pairs, version_by_task)

        # 批量查所涉考勤记录的异议信息（取最新一条，禁 N+1）
        record_ids = [r.id for r in records]
        objections_by_record: dict[int, Objection] = {}
        if record_ids:
            stmt = (
                select(Objection)
                .where(Objection.attendance_record_id.in_(record_ids))
                .order_by(Objection.id.desc())
            )
            for obj in self._session.execute(stmt).scalars().all():
                if obj.attendance_record_id not in objections_by_record:
                    objections_by_record[obj.attendance_record_id] = obj

        out: list[AttendanceResponse] = []
        for r in records:
            task: InspectionTask | None = tasks.get(r.task_id)
            sno, name = display.get((r.task_id, r.student_id), (None, None))

            # 任务时段与教室简报
            period_text = (
                f"第{task.start_period}-{task.end_period}节"
                if task and task.start_period and task.end_period
                else None
            )
            period_simple = (
                f"{task.start_period}-{task.end_period}"
                if task and task.start_period and task.end_period
                else None
            )
            task_brief = (
                AttendanceTaskBrief(
                    task_id=task.id,
                    inspection_date=task.inspection_date,
                    inspection_type=task.inspection_type,
                    course_name_snapshot=task.course_name_snapshot,
                    class_name_snapshot=task.class_name_snapshot,
                    classroom_snapshot=task.classroom_snapshot,
                    start_period=task.start_period,
                    end_period=task.end_period,
                    period_text=period_text,
                    week_no=task.week_no,
                )
                if task is not None
                else None
            )

            # 关联的异议信息
            obj = objections_by_record.get(r.id)
            has_obj = obj is not None
            obj_id = str(obj.id) if obj else None
            obj_status = obj.final_status if obj else None
            obj_summary = (
                AttendanceObjectionBrief(
                    id=str(obj.id),
                    status=obj.final_status,
                    initial_status=obj.initial_status,
                    final_status=obj.final_status,
                    desired_type=obj.desired_type,  # type: ignore[arg-type]
                    reason=obj.reason,
                    created_at=obj.created_at,
                )
                if obj
                else None
            )

            out.append(
                AttendanceResponse(
                    id=r.id,
                    task_id=r.task_id,
                    student_id=r.student_id,
                    student_no=sno,
                    name=name,
                    effective_type=r.effective_type,
                    current_version=r.current_version,
                    source_submission_item_id=r.source_submission_item_id,
                    task=task_brief,
                    created_at=r.created_at,
                    has_objection=has_obj,
                    objection_id=obj_id,
                    objection_status=obj_status,
                    objection_summary=obj_summary,
                    period=period_simple,
                    classroom=task.classroom_snapshot if task else None,
                )
            )
        return out


__all__ = ["AttendanceService"]
