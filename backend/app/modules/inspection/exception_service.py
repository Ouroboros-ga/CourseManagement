"""执行异常即时生效；不制造学生考勤，也不改写既有截止快照。"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from app.modules.inspection.schemas import InspectionTaskResponse, TaskCancelRequest
from app.modules.report.source_revision import SourceRevisionService

if TYPE_CHECKING:
    from app.modules.inspection.service import InspectionService


def _version(task: InspectionTask, body: TaskCancelRequest) -> None:
    if task.lock_version != body.lock_version:
        raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化，请刷新后重试")


def _snapshot(task: InspectionTask) -> dict[str, Any]:
    return {
        "exception_reported_at": task.exception_reported_at.isoformat()
        if task.exception_reported_at
        else None,
        "exception_reported_by": str(task.exception_reported_by)
        if task.exception_reported_by
        else None,
        "exception_reporter_name": task.exception_reporter_name,
        "exception_reason": task.exception_reason,
        "lock_version": task.lock_version,
    }


def _finish(
    service: "InspectionService",
    actor: CurrentUser,
    task: InspectionTask,
    body: TaskCancelRequest,
    request_id: str | None,
    action: str,
    before: dict[str, Any],
) -> InspectionTaskResponse:
    task.lock_version += 1
    service._repo.flush()
    SourceRevisionService.bump_for_task(service._session, task)
    service._audit(
        actor_user_id=actor.id,
        action=action,
        resource_type="inspection_task",
        resource_id=str(task.id),
        before=before,
        after={**_snapshot(task), "college_id": str(task.college_id)},
        reason=body.reason,
        request_id=request_id,
    )
    service._session.commit()
    return service._assemble_tasks([task])[0]


def report_exception(
    service: "InspectionService",
    actor: CurrentUser,
    task_id: int,
    body: TaskCancelRequest,
    request_id: str | None,
) -> InspectionTaskResponse:
    service._require(actor.id, "submission.create")
    probe = service._repo.get_task(task_id)
    if probe is None:
        raise NotFoundError("任务不存在")
    service._require_active_semester(probe.semester_id)
    task = service._require_execution_task(actor, task_id)
    _version(task, body)
    if task.exception_reported_at is not None:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已上报异常，请刷新")
    # 包括已撤回/驳回历史：有执行事实后，应走既有更正流程，不能抹成未执行异常。
    for model in (InspectionSubmission, AttendanceRecord):
        if service._session.scalar(
            see_withdrawn(select(model.id).where(model.task_id == task.id).limit(1))
        ):
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已有提交或考勤记录，不可覆盖为异常")
    day = service._repo.deadline_for_task(task)
    service._settle_assessment(task, day)
    before = _snapshot(task)
    task.exception_reported_at = utcnow()
    task.exception_reported_by = actor.id
    account = service._identity.get_user_by_id(actor.id)
    assert account is not None  # _require_execution_task 已在本事务内锁定并核实账号
    task.exception_reporter_name = account.display_name
    task.exception_reason = body.reason
    return _finish(
        service, actor, task, body, request_id, "inspection.task.exception.report", before
    )


def clear_exception(
    service: "InspectionService",
    actor: CurrentUser,
    task_id: int,
    body: TaskCancelRequest,
    request_id: str | None,
) -> InspectionTaskResponse:
    service._require(actor.id, "inspection.cancel")
    probe = service._repo.get_task(task_id)
    if probe is None:
        raise NotFoundError("任务不存在")
    service._require_active_semester(probe.semester_id)
    task = service._repo.get_task_for_update(task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    _version(task, body)
    if task.exception_reported_at is None or task.canceled_at is not None:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "当前任务不能恢复异常")
    service._settle_assessment(task, service._repo.deadline_for_task(task))
    before = _snapshot(task)
    task.exception_reported_at = task.exception_reported_by = None
    task.exception_reporter_name = task.exception_reason = None
    return _finish(
        service, actor, task, body, request_id, "inspection.task.exception.clear", before
    )
