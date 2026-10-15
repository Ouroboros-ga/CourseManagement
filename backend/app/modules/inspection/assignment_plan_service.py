"""Freeze a proposed allocation; confirm exact warnings before one atomic commit."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester, VolunteerQualification
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
from app.modules.inspection.assignment_plan_schemas import (
    AssignmentPlanCommit,
    AssignmentPlanPreview,
)
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    AssignMethod,
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
)
from app.modules.inspection.scheduling.loader import REASONS, load_snapshot
from app.modules.inspection.scheduling.planner import plan_assignments
from app.modules.inspection.scheduling.validation import validate_plan
from app.modules.inspection.scoped_service import ScopedInspectionService
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.member_models import VolunteerGroupMember
from app.modules.volunteer.models import VolunteerGroup


class AssignmentPlanService:
    def __init__(self, db, actor, cid, gid):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid
        self.inspection = ScopedInspectionService(db, actor, cid)

    def _context(self, semester_id):
        scope = resolve_scope(self.db, self.actor, self.cid, "assignment.manage", write=True)
        self.scope = scope
        self.inspection._repo.college_ids = frozenset({self.cid})
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == semester_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        group = self.db.scalar(
            select(VolunteerGroup)
            .where(
                VolunteerGroup.id == self.gid,
                VolunteerGroup.college_id == self.cid,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            semester is None
            or semester.status != "ACTIVE"
            or group is None
            or group.status != "ACTIVE"
        ):
            raise ConflictError(message="学期或执行组已失效，请刷新")
        return scope, semester, group

    def _targets(self, semester_id, task_ids, *, lock=False):
        statement = (
            select(InspectionTask)
            .where(
                InspectionTask.id.in_(task_ids),
                InspectionTask.college_id == self.cid,
                InspectionTask.group_id == self.gid,
                InspectionTask.semester_id == semester_id,
                self.scope.task_condition(),
            )
            .order_by(InspectionTask.id)
        )
        if lock:
            statement = statement.with_for_update()
        tasks = list(self.db.scalars(statement.execution_options(populate_existing=True)))
        if {task.id for task in tasks} != set(task_ids):
            raise NotFoundError("计划包含不可见、其他组或其他学期的任务")
        if any(task.canceled_at is not None for task in tasks):
            raise ConflictError(message="计划任务已取消")
        if self.db.scalar(
            select(InspectionSubmission.id)
            .where(
                InspectionSubmission.task_id.in_(task_ids),
                InspectionSubmission.review_status.in_(["PENDING", "APPROVED"]),
            )
            .limit(1)
        ):
            raise ConflictError(message="任务已有待审核或正式提交，不能通过排班计划改派")
        return tasks

    def _revision(self, scope, group, tasks, snapshot):
        return fingerprint(
            {
                "actor": self.actor.id,
                "college": self.cid,
                "group": [group.id, group.lock_version, group.config_version],
                "authorization": scope.authorization_revision,
                "tasks": [(task.id, task.lock_version, task.roster_version) for task in tasks],
                "snapshot": snapshot,
                "caps": [
                    get_settings().assignment_max_tasks_per_day,
                    get_settings().assignment_max_tasks_per_week,
                ],
            }
        )

    @atomic_write
    def preview(self, data):
        body = validated(AssignmentPlanPreview, data)
        scope, semester, group = self._context(int(body.semester_id))
        tasks = self._targets(semester.id, [int(value) for value in body.task_ids])
        manual = body.assignments is not None
        current = {task.id: self.inspection._repo.get_assignment_by_task(task.id) for task in tasks}
        if not manual and any(current.values()):
            raise ConflictError(message="自动计划包含已排班任务，请刷新；人工改派须明确候选人")
        candidates = (
            sorted({int(value) for value in body.assignments.values()})
            if manual
            else (
                list(
                    self.db.scalars(
                        select(UserAccount.id)
                        .join(
                            VolunteerGroupMember,
                            VolunteerGroupMember.student_id == UserAccount.student_id,
                        )
                        .join(
                            VolunteerQualification,
                            VolunteerQualification.student_id == UserAccount.student_id,
                        )
                        .join(UserRole, UserRole.user_id == UserAccount.id)
                        .join(Role, Role.id == UserRole.role_id)
                        .where(
                            VolunteerGroupMember.college_id == self.cid,
                            VolunteerGroupMember.group_id == self.gid,
                            VolunteerGroupMember.semester_id == semester.id,
                            VolunteerGroupMember.status == "ACTIVE",
                            VolunteerGroupMember.effective_from
                            <= max(t.inspection_date for t in tasks),
                            VolunteerGroupMember.effective_to
                            > min(t.inspection_date for t in tasks),
                            VolunteerQualification.semester_id == semester.id,
                            VolunteerQualification.enabled.is_(True),
                            UserAccount.status == "ACTIVE",
                            Role.code == "VOLUNTEER",
                        )
                        .distinct()
                        .order_by(UserAccount.id)
                        .limit(501)
                    )
                )
            )
        )
        if len(candidates) > 500:
            raise ConflictError(message="单次计划最多500名候选人，请缩小范围")
        snapshot = load_snapshot(self.db, semester, tasks, candidates, lock_inputs=True)
        settings = get_settings()
        if manual:
            assignments = {int(key): int(value) for key, value in body.assignments.items()}
            failure = validate_plan(
                snapshot,
                assignments,
                day_cap=settings.assignment_max_tasks_per_day,
                week_cap=settings.assignment_max_tasks_per_week,
            )
            if failure:
                raise ConflictError(
                    message=f"不能生成该人工计划：{REASONS.get(failure[1], failure[1])}"
                )
            unassigned = {}
        else:
            result = plan_assignments(
                snapshot.tasks,
                snapshot.volunteers,
                day_cap=settings.assignment_max_tasks_per_day,
                week_cap=settings.assignment_max_tasks_per_week,
            )
            assignments, unassigned = result.assignments, result.unassigned
        assigned = [
            {
                "task_id": str(tid),
                "volunteer_user_id": str(vid),
                "warning_codes": list(snapshot.warnings.get((tid, vid), ())),
            }
            for tid, vid in sorted(assignments.items())
        ]
        payload = {
            "task_ids": [task.id for task in tasks],
            "candidate_ids": candidates,
            "assigned": assigned,
            "manual": manual,
            "reason": body.reason,
            "previous": {
                str(tid): [row.id, row.lock_version, row.volunteer_user_id] if row else None
                for tid, row in current.items()
            },
            "unassigned": [
                {
                    "task_id": str(tid),
                    "reason_code": snapshot.static_failures.get(tid, code),
                    "message": REASONS.get(snapshot.static_failures.get(tid, code), code),
                }
                for tid, code in sorted(unassigned.items())
            ],
        }
        row = AssignmentConfirmationPlan(
            id=str(uuid4()),
            actor_user_id=self.actor.id,
            college_id=self.cid,
            group_id=self.gid,
            semester_id=semester.id,
            revision=self._revision(scope, group, tasks, snapshot),
            expires_at=utcnow() + timedelta(minutes=10),
            payload=payload,
        )
        self.db.add(row)
        self.db.flush()
        response = {
            "id": row.id,
            "revision": row.revision,
            "expires_at": row.expires_at.isoformat() + "Z",
            "assigned": assigned,
            "unassigned": payload["unassigned"],
        }
        self.db.commit()
        return response

    @atomic_write
    def commit(self, plan_id, data, request_id=None):
        body = validated(AssignmentPlanCommit, data)
        row = self.db.scalar(
            select(AssignmentConfirmationPlan).where(
                AssignmentConfirmationPlan.id == plan_id,
                AssignmentConfirmationPlan.actor_user_id == self.actor.id,
                AssignmentConfirmationPlan.college_id == self.cid,
                AssignmentConfirmationPlan.group_id == self.gid,
            )
        )
        if row is None:
            raise NotFoundError("排班计划不存在或不属于当前操作者")
        scope, semester, group = self._context(row.semester_id)
        row = self.db.scalar(
            select(AssignmentConfirmationPlan)
            .where(AssignmentConfirmationPlan.id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if body.revision != row.revision:
            raise ConflictError(message="计划修订不匹配，请重新预览")
        if row.status == "COMMITTED":
            result = row.result
            self.db.commit()
            return result
        if row.expires_at <= utcnow():
            raise ConflictError(message="计划已过期，请重新预览")
        payload = row.payload
        assignments = {
            int(item["task_id"]): int(item["volunteer_user_id"]) for item in payload["assigned"]
        }
        required = {
            (item["task_id"], item["volunteer_user_id"], tuple(sorted(item["warning_codes"])))
            for item in payload["assigned"]
            if item["warning_codes"]
        }
        confirmed = [
            (item.task_id, item.volunteer_user_id, tuple(sorted(item.warning_codes)))
            for item in body.confirmations
        ]
        if len(set(confirmed)) != len(confirmed) or set(confirmed) != required:
            raise ConflictError(message="请明确确认计划中每项任务及人员的具体警告")
        initial_tasks = self._targets(semester.id, payload["task_ids"])
        anchors = {
            (assignments[task.id], task.inspection_date)
            for task in initial_tasks
            if task.id in assignments
        }
        for task in initial_tasks:
            previous = payload["previous"][str(task.id)]
            if previous:
                anchors.add((previous[2], task.inspection_date))
        self.inspection._lock_day_anchors(anchors)
        tasks = self._targets(semester.id, payload["task_ids"], lock=True)
        existing = {
            task.id: self.inspection._repo.get_assignment_by_task_for_update(task.id)
            for task in tasks
        }
        for tid, active in existing.items():
            value = [active.id, active.lock_version, active.volunteer_user_id] if active else None
            if value != payload["previous"][str(tid)]:
                raise ConflictError(message="任务受派已变化，请重新预览")
        snapshot = load_snapshot(
            self.db, semester, tasks, payload["candidate_ids"], lock_inputs=True
        )
        if row.revision != self._revision(scope, group, tasks, snapshot):
            raise ConflictError(message="任务、课程、成员、授权或负载已变化，请重新预览")
        failure = validate_plan(
            snapshot,
            assignments,
            day_cap=get_settings().assignment_max_tasks_per_day,
            week_cap=get_settings().assignment_max_tasks_per_week,
        )
        if failure:
            raise ConflictError(message=f"计划校验失败：{REASONS.get(failure[1], failure[1])}")
        for task in tasks:
            if task.id not in assignments:
                continue
            old = existing[task.id]
            if old:
                old.revoked_at = utcnow()
                old.lock_version += 1
                self.db.flush()
                for request in self.db.scalars(
                    select(AssignmentChangeRequest)
                    .where(
                        AssignmentChangeRequest.assignment_id == old.id,
                        AssignmentChangeRequest.status == "PENDING",
                    )
                    .with_for_update()
                ):
                    request.status, request.processed_by, request.processed_at = (
                        "APPROVED",
                        self.actor.id,
                        utcnow(),
                    )
                    request.comment = payload["reason"] or "管理员已通过确认计划改派"
            self.db.add(
                InspectionAssignment(
                    task_id=task.id,
                    volunteer_user_id=assignments[task.id],
                    assign_method=AssignMethod.MANUAL.value
                    if payload["manual"]
                    else AssignMethod.AUTO.value,
                    assign_reason=payload["reason"],
                    assigned_by=self.actor.id,
                    lock_version=0,
                )
            )
            task.lock_version += 1
        result = {
            "semester_id": str(semester.id),
            "target_task_count": len(tasks),
            "assigned_count": len(assignments),
            "unassigned_count": len(payload["unassigned"]),
            "assigned": payload["assigned"],
            "unassigned": payload["unassigned"],
        }
        self.inspection._audit(
            actor_user_id=self.actor.id,
            action="assignment.plan.commit",
            resource_type="assignment_confirmation_plan",
            resource_id=row.id,
            after={
                "revision": row.revision,
                "confirmed": [item.model_dump() for item in body.confirmations],
                "result": result,
            },
            reason=payload["reason"],
            request_id=request_id,
        )
        row.status, row.result = "COMMITTED", result
        self.db.commit()
        return result
