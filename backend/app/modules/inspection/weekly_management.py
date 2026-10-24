"""Logged-in weekly management projections; reads never execute a workflow."""

from copy import deepcopy

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import iso_utc, utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import AdministrativeClass, Semester
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
from app.modules.inspection.assignment_plan_service import AssignmentPlanService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.scheduling.loader import load_snapshot
from app.modules.inspection.scheduling.validation import validate_plan
from app.modules.inspection.weekly_models import WeeklyInspectionExecution
from app.modules.inspection.weekly_service import (
    WeeklyInspectionService,
    configuration_permitted,
)
from app.modules.organization.service import atomic_write
from app.modules.volunteer.models import VolunteerGroup
from app.modules.volunteer.preparation_models import semester_group_config


class WeeklyManagementService:
    def __init__(self, db, cid, gid, sid):
        self.db, self.cid, self.gid, self.sid = db, cid, gid, sid
        self.domain = WeeklyInspectionService(db, cid, gid, sid)

    def _context(self, actor):
        self.domain._enabled()
        scopes = tuple(resolve_scope(self.db, actor, self.cid, action) for action in (
            "inspection.generate", "assignment.manage",
        ))
        semester = self.db.get(Semester, self.sid, populate_existing=True)
        group = self.db.scalar(select(VolunteerGroup).where(
            VolunteerGroup.id == self.gid, VolunteerGroup.college_id == self.cid,
        ).execution_options(populate_existing=True))
        if semester is None or group is None:
            raise NotFoundError("学期或执行组不在当前范围")
        plan = self.domain._plan()
        version = semester_group_config(self.db, group, self.sid)
        for scope in scopes:
            if scope.unrestricted or scope.permits_group(self.gid):
                continue
            if plan and configuration_permitted((scope,), self.gid, plan.configuration):
                continue
            if version:
                config = version.configuration
                classes = (
                    {int(v) for v in config["class_ids"]}
                    if config["class_mode"] == "SPECIFIC" else set(self.db.scalars(
                        select(AdministrativeClass.id).where(
                            AdministrativeClass.college_id == self.cid,
                        )
                    ))
                )
                if classes and any(scope.permits_plan(self.gid, int(tid), set(), classes)
                                   for tid in config["course_type_ids"]):
                    continue
            raise NotFoundError("执行组不在当前授权范围")
        return scopes, semester, group

    def _visible(self, row, scopes):
        if not configuration_permitted(scopes, self.gid, row.configuration["policy"]):
            return False
        ids = {int(v) for v in row.task_ids}
        if not ids:
            return True
        visible = set(self.db.scalars(select(InspectionTask.id).where(
            InspectionTask.id.in_(ids), InspectionTask.college_id == self.cid,
            InspectionTask.group_id == self.gid, InspectionTask.semester_id == self.sid,
            *(scope.task_condition() for scope in scopes),
        )))
        return visible == ids

    def _run(self, eid, scopes, *, lock=False):
        plan = self.domain._plan(lock=lock)
        if plan is None:
            raise NotFoundError()
        query = select(WeeklyInspectionExecution).where(
            WeeklyInspectionExecution.id == eid, WeeklyInspectionExecution.plan_id == plan.id,
        )
        if lock:
            query = query.with_for_update()
        row = self.db.scalar(query.execution_options(populate_existing=True))
        if row is None or not self._visible(row, scopes):
            raise NotFoundError("本周期不在当前授权范围")
        return row

    def policy(self, actor):
        scopes, semester, group = self._context(actor)
        row = self.domain._plan()
        if row and not configuration_permitted(scopes, self.gid, row.configuration):
            raise NotFoundError("每周计划不在当前授权范围")
        return {
            "plan": self.domain.plan_dto(row) if row else None,
            "semester_status": semester.status, "group_status": group.status,
            "publication_mode": "DRAFT_ONLY",
        }

    def history(self, actor, *, limit=20, before_id=None):
        scopes, _, _ = self._context(actor)
        plan = self.domain._plan()
        if plan is None:
            return {"items": [], "next_before_id": None}
        query = select(WeeklyInspectionExecution).where(
            WeeklyInspectionExecution.plan_id == plan.id,
        )
        if before_id is not None:
            query = query.where(WeeklyInspectionExecution.id < before_id)
        # At most 60 effective teaching weeks exist per plan; don't leak hidden-row counts.
        rows = self.db.scalars(query.order_by(WeeklyInspectionExecution.id.desc()).limit(60))
        visible = [row for row in rows if self._visible(row, scopes)]
        items = [{
            "id": str(row.id), "target_week": row.target_week, "status": row.status,
            "reason_code": row.reason_code, "date_from": row.date_from.isoformat(),
            "date_to": row.date_to.isoformat(), "due_at": iso_utc(row.due_at),
            "task_count": len(row.task_ids), "assignment_plan_id": row.assignment_plan_id,
        } for row in visible[:limit]]
        return {
            "items": items,
            "next_before_id": items[-1]["id"] if len(visible) > limit else None,
        }

    def detail(self, actor, eid):
        scopes, semester, group = self._context(actor)
        row = self._run(eid, scopes)
        result = self.domain.execution_dto(row)
        coverage = self.domain._saved_coverage(row)
        skipped = coverage["already_assigned"]
        current = {
            str(item.task_id): str(item.id) for item in self.db.scalars(
                select(InspectionAssignment).where(
                    InspectionAssignment.task_id.in_([int(v["task_id"]) for v in skipped]),
                    InspectionAssignment.revoked_at.is_(None),
                ).execution_options(populate_existing=True)
            )
        }
        changes = [{
            "task_id": item["task_id"], "expected_assignment_id": item["assignment_id"],
            "current_assignment_id": current.get(item["task_id"]),
        } for item in skipped if current.get(item["task_id"]) != item["assignment_id"]]
        result.update({
            "coverage_status": "CHANGED" if changes else "CURRENT",
            "coverage_changes": changes, "can_confirm": False,
            "requires_recheck": bool(changes),
        })
        if row.assignment_plan_id:
            draft = self.db.scalar(select(AssignmentConfirmationPlan).where(
                AssignmentConfirmationPlan.id == row.assignment_plan_id,
                AssignmentConfirmationPlan.college_id == self.cid,
                AssignmentConfirmationPlan.group_id == self.gid,
                AssignmentConfirmationPlan.semester_id == self.sid,
            ).execution_options(populate_existing=True))
            if draft is None or set(draft.payload["task_ids"]) != {
                int(v) for v in coverage["draft_task_ids"]
            }:
                raise NotFoundError("原草案与周期任务不一致")
            owner = draft.actor_user_id == actor.id
            ready = bool(
                owner and draft.status == "READY" and draft.expires_at > utcnow()
                and semester.status == group.status == "ACTIVE"
                and self._draft_current(actor, scopes[1], semester, group, draft)
            )
            result.update({
                "assignment_plan_status": draft.status,
                "draft_expires_at": iso_utc(draft.expires_at),
                "can_confirm": bool(ready and not changes),
                "requires_recheck": bool(changes or (draft.status != "COMMITTED"
                                                       and (not owner or not ready))),
            })
            if draft.status == "COMMITTED":
                result["publication_result"] = deepcopy(draft.result)
        return result

    def _draft_current(self, actor, scope, semester, group, draft):
        """Read-only point-in-time check; original commit still repeats checks under locks."""
        plans = AssignmentPlanService(self.db, actor, self.cid, self.gid)
        plans.scope = scope
        plans.inspection._repo.college_ids = frozenset({self.cid})
        try:
            tasks = plans._targets(self.sid, draft.payload["task_ids"])
            for task in tasks:
                active = plans.inspection._repo.get_assignment_by_task(task.id)
                current = (
                    [active.id, active.lock_version, active.volunteer_user_id] if active else None
                )
                if current != draft.payload["previous"][str(task.id)]:
                    return False
            snapshot = load_snapshot(self.db, semester, tasks, draft.payload["candidate_ids"])
            if draft.revision != plans._revision(scope, group, tasks, snapshot):
                return False
            assignments = {
                int(item["task_id"]): int(item["volunteer_user_id"])
                for item in draft.payload["assigned"]
            }
            settings = get_settings()
            return validate_plan(
                snapshot, assignments, day_cap=settings.assignment_max_tasks_per_day,
                week_cap=settings.assignment_max_tasks_per_week,
            ) is None
        except (ConflictError, NotFoundError):
            # Changed classification/rules invalidate confirmation, not historical access.
            return False

    @atomic_write
    def register_due(self, actor, current_version):
        scopes = self.domain._context(actor)[:2]
        plan = self.domain._plan(lock=True)
        if plan is None or not configuration_permitted(scopes, self.gid, plan.configuration):
            raise NotFoundError()
        if plan.version != current_version:
            raise ConflictError(message="每周计划已变化，请刷新后重试")
        return self.domain.register_due(plan.id)

    @atomic_write
    def recheck(self, actor, eid, expected_assignment_plan_id):
        scopes = self.domain._context(actor)[:2]
        row = self._run(eid, scopes, lock=True)
        if row.assignment_plan_id != expected_assignment_plan_id:
            raise ConflictError(message="本周草案已变化，请重新读取结果")
        return self.domain.refresh_draft(actor, eid)
