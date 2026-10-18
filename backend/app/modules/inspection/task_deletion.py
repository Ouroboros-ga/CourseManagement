"""Explicit deletion plans separate mistaken tasks from immutable execution history."""

from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester
from app.modules.attendance.models import AttendanceRecord
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    TaskDeadlineAssessment,
)
from app.modules.inspection.permissions import GENERATE_PERMISSION
from app.modules.organization.impact_models import ConfigurationImpactItem


def preview(service, actor, ids):
    service._require(actor.id, GENERATE_PERMISSION)
    db = service._session
    ids = sorted(set(ids))
    if not 1 <= len(ids) <= 500 or any(not 0 < i < 2**63 for i in ids):
        raise ConflictError(message="请选择1至500个有效任务")
    # Keep the established semester -> task lock order.
    sids = list(
        db.scalars(
            service._repo.scoped_tasks()
            .where(InspectionTask.id.in_(ids))
            .with_only_columns(InspectionTask.semester_id)
        )
    )
    semesters = {
        row.id: row.status
        for row in db.scalars(
            select(Semester)
            .where(Semester.id.in_(sids))
            .order_by(Semester.id)
            .with_for_update(read=True)
        )
    }
    tasks = list(
        db.scalars(
            service._repo.scoped_tasks()
            .where(InspectionTask.id.in_(ids))
            .order_by(InspectionTask.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if {t.id for t in tasks} != set(ids):
        raise NotFoundError("请求包含不存在或未授权的任务，整批未执行")
    retained = set()
    for model in (
        AttendanceRecord,
        InspectionSubmission,
        TaskDeadlineAssessment,
        ConfigurationImpactItem,
    ):
        # Permission reads may already have established an RR snapshot. Current reads
        # must see execution facts committed before we acquired the task locks.
        retained.update(
            db.scalars(
                select(model.task_id).where(model.task_id.in_(ids)).with_for_update(read=True)
            )
        )
    retained.update(
        t.id for t in tasks if semesters.get(t.semester_id) == "ARCHIVED" or t.deleted_at
    )
    plan = {
        "retained_ids": [str(i) for i in ids if i in retained],
        "permanent_ids": [str(i) for i in ids if i not in retained],
        "history_preserved": True,
    }
    plan["revision"] = fingerprint(
        {
            "tasks": [[t.id, t.lock_version, str(t.deleted_at)] for t in tasks],
            "semesters": semesters,
            "plan": plan,
        }
    )
    return tasks, plan


def apply(service, actor, ids, reason, request_id, revision):
    tasks, plan = preview(service, actor, ids)
    task_ids = [t.id for t in tasks]
    if revision != plan["revision"] and (revision is not None or plan["retained_ids"]):
        raise ConflictError(message="删除影响已变化，请重新预览后确认；force不能擦除历史")
    db = service._session
    # No new execution fact can appear while these task locks are held.
    for task in tasks:
        if str(task.id) not in plan["retained_ids"] or task.deleted_at is not None:
            continue
        before = {"task_key": task.task_key, "lock_version": task.lock_version}
        task.deleted_at = utcnow()
        task.lock_version += 1
        service._audit(
            actor_user_id=actor.id,
            action="inspection.task.delete_retained",
            resource_type="inspection_task",
            resource_id=str(task.id),
            before=before,
            after={"history_preserved": True},
            reason=reason,
            request_id=request_id,
        )
    if plan["permanent_ids"]:
        # The legacy cleaner owns the only commit; retained mutations share its transaction.
        service._legacy_delete_tasks(
            actor, [int(i) for i in plan["permanent_ids"]], reason=reason, request_id=request_id
        )
    else:
        db.commit()
    service._last_deletion_result = plan
    return task_ids


def restore(service, actor, task_id, version):
    tasks, _ = preview(service, actor, [task_id])
    task = tasks[0]
    if task.deleted_at is None or task.lock_version != version:
        raise ConflictError(message="删除记录已变化，请刷新后恢复")
    before = {"deleted_at": str(task.deleted_at), "lock_version": task.lock_version}
    task.deleted_at = None
    task.lock_version += 1
    service._audit(
        actor_user_id=actor.id,
        action="inspection.task.restore_deleted",
        resource_type="inspection_task",
        resource_id=str(task.id),
        before=before,
        after={"history_preserved": True},
        reason=None,
        request_id=None,
    )
    service._session.commit()
    return service._assemble_tasks([task])[0].model_dump()
