"""Record changes with their transaction; resolve explicitly through existing rules."""
from typing import Literal

from pydantic import Field
from sqlalchemy import func, select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.organization.impact_models import ConfigurationImpactItem
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated


class ImpactDecision(StrictModel):
    decision: Literal["KEEP", "CANCEL", "REASSIGNED"]
    lock_version: int = Field(ge=1)
    task_lock_version: int = Field(ge=0)
    assignment_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=512)


def assignment_snapshot(db, task_ids, *, lock=False):
    stmt = select(InspectionAssignment).where(InspectionAssignment.task_id.in_(task_ids),
        InspectionAssignment.revoked_at.is_(None)).order_by(InspectionAssignment.task_id, InspectionAssignment.id)
    if lock:
        stmt = stmt.with_for_update(read=True)
    return {row.task_id: {"id": str(row.id), "volunteer_user_id": str(row.volunteer_user_id), "lock_version": row.lock_version}
            for row in db.scalars(stmt.execution_options(populate_existing=True))}


def capture_impacts(db, cid, kind, source_id, source_version, *, task_ids=None, before=None, after=None):
    from app.modules.organization.future_impact import business_today
    query = select(InspectionTask).where(InspectionTask.college_id == cid,
        InspectionTask.inspection_date >= business_today(), InspectionTask.canceled_at.is_(None))
    if task_ids is not None:
        query = query.where(InspectionTask.id.in_(task_ids))
    else:
        column = {"group": InspectionTask.group_id, "course_type": InspectionTask.course_type_id_snapshot,
                  "college": InspectionTask.college_id}[kind]
        query = query.where(column == int(source_id))
    tasks = list(db.scalars(query.order_by(InspectionTask.id).with_for_update().execution_options(populate_existing=True)))
    assignments = assignment_snapshot(db, [task.id for task in tasks], lock=True)
    for task in tasks:
        db.add(ConfigurationImpactItem(college_id=cid, task_id=task.id, source_kind=kind,
            source_id=str(source_id), source_version=source_version,
            snapshot={"task_lock_version": task.lock_version, "assignment": assignments.get(task.id),
                "inspection_date": task.inspection_date.isoformat(), "course_name": task.course_name_snapshot,
                "group_id": str(task.group_id) if task.group_id else None,
                "activity_start_at": task.activity_start_at.isoformat() if task.activity_start_at else None,
                "activity_end_at": task.activity_end_at.isoformat() if task.activity_end_at else None,
                "source_before": before, "source_after": after}))


class ConfigurationImpactService:
    def __init__(self, db, actor, cid):
        self.db, self.actor, self.cid = db, actor, cid

    def _dto(self, row, task, assignment):
        return {"id": str(row.id), "task_id": str(row.task_id), "source_kind": row.source_kind,
                "source_id": row.source_id, "source_version": row.source_version,
                "snapshot": row.snapshot, "status": row.status, "lock_version": row.lock_version,
                "current_task_lock_version": task.lock_version, "canceled": task.canceled_at is not None,
                "current_assignment": assignment, "assignment_revision": fingerprint(assignment),
                "decided_by": str(row.decided_by) if row.decided_by else None,
                "decision": row.decision}

    def list(self, *, page=1, page_size=50, status=None):
        scope = resolve_scope(self.db, self.actor, self.cid, "inspection.read")
        stmt = select(ConfigurationImpactItem, InspectionTask).join(InspectionTask, InspectionTask.id == ConfigurationImpactItem.task_id).where(
            ConfigurationImpactItem.college_id == self.cid, scope.task_condition())
        if status:
            stmt = stmt.where(ConfigurationImpactItem.status == status)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        pairs = list(self.db.execute(stmt.order_by(ConfigurationImpactItem.id.desc()).offset((page-1)*page_size).limit(page_size)))
        assignments = assignment_snapshot(self.db, [task.id for _, task in pairs])
        return {"items": [self._dto(row, task, assignments.get(task.id)) for row, task in pairs], "total": total}

    @atomic_write
    def resolve(self, item_id, data):
        body = validated(ImpactDecision, data)
        action = {"KEEP": "inspection.generate", "CANCEL": "inspection.cancel", "REASSIGNED": "assignment.manage"}[body.decision]
        # Parent authorization first, then task and work item: same order as business writes.
        scope = resolve_scope(self.db, self.actor, self.cid, action, write=True)
        probe = self.db.scalar(select(ConfigurationImpactItem).where(ConfigurationImpactItem.id == item_id,
            ConfigurationImpactItem.college_id == self.cid))
        if probe is None:
            raise NotFoundError()
        task = self.db.scalar(select(InspectionTask).where(InspectionTask.id == probe.task_id, scope.task_condition()).with_for_update().execution_options(populate_existing=True))
        if task is None:
            raise NotFoundError()
        row = self.db.scalar(select(ConfigurationImpactItem).where(ConfigurationImpactItem.id == item_id).with_for_update().execution_options(populate_existing=True))
        assignment = assignment_snapshot(self.db, [task.id], lock=True).get(task.id)
        if row.status != "OPEN" or row.lock_version != body.lock_version or task.lock_version != body.task_lock_version or fingerprint(assignment) != body.assignment_revision:
            raise ConflictError(message="影响项、任务或受派已变化，请刷新后重新确认")
        if body.decision == "CANCEL":
            from app.modules.inspection.schemas import TaskCancelRequest
            from app.modules.inspection.scoped_service import ScopedInspectionService
            if task.canceled_at is None:
                ScopedInspectionService(self.db, self.actor, self.cid).cancel_task(self.actor, task.id,
                    TaskCancelRequest(lock_version=task.lock_version, reason=body.note), None, commit=False)
        elif body.decision == "REASSIGNED":
            if assignment is None or assignment.get("id") == (row.snapshot.get("assignment") or {}).get("id") or task.canceled_at is not None:
                raise ConflictError(message="请先通过排班确认流程完成新的有效受派，再登记改派处置")
        elif task.canceled_at is not None:
            raise ConflictError(message="任务已取消，不能登记保留，请选择取消处置")
        row.status, row.decided_by, row.decided_at = body.decision, self.actor.id, utcnow()
        row.lock_version += 1
        row.decision = {"note": body.note, "task_lock_version": task.lock_version, "assignment": assignment}
        self.db.add(AuditLog(actor_user_id=self.actor.id, action="campus.impact.resolve", resource_type="configuration_impact_item",
            resource_id=str(row.id), after_json=scoped_snapshot(row.decision | {"status": row.status}, self.cid)))
        self.db.flush()
        result = self._dto(row, task, assignment)
        self.db.commit()
        return result
