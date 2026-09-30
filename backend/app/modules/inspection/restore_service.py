"""仅恢复未开始、未形成执行事实且基础快照仍兼容的取消任务。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.modules.attendance.models import AttendanceRecord
from app.modules.inspection import permissions as perms
from app.modules.inspection.models import InspectionSubmission, TaskDeadlineAssessment
from app.modules.inspection.schemas import InspectionGenerateRequest, TaskCancelRequest

if TYPE_CHECKING:
    from app.modules.identity.service import CurrentUser
    from app.modules.inspection.schemas import InspectionTaskResponse
    from app.modules.inspection.service import InspectionService


def restore_task(
    service: InspectionService,
    actor: CurrentUser,
    task_id: int,
    body: TaskCancelRequest,
    request_id: str | None,
) -> InspectionTaskResponse:
    service._session.rollback()
    service._session.connection(execution_options={"isolation_level": "READ COMMITTED"})
    service._require(actor.id, perms.GENERATE_PERMISSION)
    probe = service._repo.get_task(task_id)
    if probe is None:
        raise NotFoundError("任务不存在")
    sem = service._require_active_semester(probe.semester_id)
    task = service._repo.get_task_for_update(task_id)
    assert task is not None
    if task.lock_version != body.lock_version:
        raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化")
    if task.canceled_at is None:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "任务未取消")
    now = utcnow()
    periods = {p.period_no: p for p in service._academic.list_period_definitions(sem.id)}
    start = periods.get(task.start_period)
    if (
        start is None
        or start.start_time is None
        or (
            datetime.combine(task.inspection_date, start.start_time) - service._deadline_offset()
            <= now
        )
    ):
        raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已开始或缺少开始时刻，不能恢复")
    for model in (InspectionSubmission, AttendanceRecord, TaskDeadlineAssessment):
        if (
            service._session.execute(
                select(model.id).where(model.task_id == task.id).limit(1).with_for_update()
            ).first()
            is not None
        ):
            raise ConflictError(ErrorCode.STATE_CONFLICT, "已有提交、考勤或截止考核，不可恢复")
    day = service._repo.get_deadline_day(task.semester_id, task.inspection_date)
    end = periods.get(task.end_period)
    if (
        day is None
        or day.deadline_at <= now
        or end is None
        or end.end_time is None
        or (
            day.deadline_at
            < datetime.combine(task.inspection_date, end.end_time) - service._deadline_offset()
        )
    ):
        raise ConflictError(ErrorCode.STATE_CONFLICT, "截止时间已失效，请重新规划")
    if task.inspection_type == "COURSE":
        request = InspectionGenerateRequest(
            semester_id=sem.id,
            inspection_type="COURSE",
            date_from=task.inspection_date,
            date_to=task.inspection_date,
            teaching_class_ids=[task.teaching_class_id] if task.teaching_class_id else [],
            require_photo=task.require_photo_snapshot,
        )
    else:
        request = InspectionGenerateRequest(
            semester_id=sem.id,
            inspection_type=task.inspection_type,
            date_from=task.inspection_date,
            date_to=task.inspection_date,
            administrative_class_ids=[task.administrative_class_id]
            if task.administrative_class_id
            else [],
            start_period=task.start_period,
            end_period=task.end_period,
            require_photo=task.require_photo_snapshot,
        )
    match = next(
        (i for i in service._build_plan_no_semlock(sem, request) if i.task_key == task.task_key),
        None,
    )
    members = service._repo.list_roster_members(task.id, task.roster_version)

    def roster_key(rows):  # noqa: ANN001, ANN202
        return sorted(
            (r.student_id, r.student_no, r.name, r.class_name_snapshot, r.grade_year_snapshot)
            for r in rows
        )

    if (
        match is None
        or roster_key(match.roster) != roster_key(members)
        or (match.course_name_snapshot, match.class_name_snapshot, match.classroom_snapshot)
        != (task.course_name_snapshot, task.class_name_snapshot, task.classroom_snapshot)
    ):
        raise ConflictError(ErrorCode.STATE_CONFLICT, "课表或名单快照已变化，请重新规划")
    assignment = service._repo.get_assignment_by_task_for_update(task.id)
    if assignment is not None:
        assignment.revoked_at = now
    before = {
        "canceled_at": task.canceled_at.isoformat(),
        "lock_version": task.lock_version,
        "assignment_id": str(assignment.id) if assignment else None,
    }
    task.canceled_at = None
    task.canceled_by = None
    task.cancel_reason = None
    task.lock_version += 1
    service._repo.flush()
    service._audit(
        actor_user_id=actor.id,
        action="inspection.task.restore",
        resource_type="inspection_task",
        resource_id=str(task.id),
        before=before,
        after={"lock_version": task.lock_version, "assigned": False},
        reason=body.reason,
        request_id=request_id,
    )
    service._session.commit()
    return service._assemble_tasks([task])[0]
