"""Policy-bound automatic reassignment, sharing the existing planner and transaction core."""

from dataclasses import replace

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.audit.models import AuditLog
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.inspection.assignment_plan_service import AssignmentPlanService, AutoChangeOrigin
from app.modules.inspection.automation_models import AutoChangeExecution, AutoChangePolicy
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionTask,
)
from app.modules.inspection.scheduling.loader import load_snapshot
from app.modules.inspection.scheduling.planner import plan_assignments
from app.modules.organization.service import atomic_write


class AutoChangeService:
    def __init__(self, db, college_id: int, group_id: int, semester_id: int):
        self.db, self.cid, self.gid, self.sid = db, college_id, group_id, semester_id

    def _enabled(self):
        if not get_settings().agent_auto_change_enabled:
            raise NotFoundError("自动换班能力尚未启用")

    def _policy(self, *, lock=False):
        query = select(AutoChangePolicy).where(
            AutoChangePolicy.college_id == self.cid,
            AutoChangePolicy.group_id == self.gid,
            AutoChangePolicy.semester_id == self.sid,
        )
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query.execution_options(populate_existing=True))

    @staticmethod
    def policy_dto(policy):
        return {
            "enabled": policy.enabled if policy else False,
            "version": policy.version if policy else 0,
            "authorizer_user_id": str(policy.authorizer_user_id) if policy else None,
        }

    @atomic_write
    def set_policy(self, actor, *, enabled: bool, current_version: int):
        self._enabled()
        AssignmentPlanService(self.db, actor, self.cid, self.gid)._context(self.sid)
        resolve_scope(self.db, actor, self.cid, "assignment.change_review", write=True)
        policy = self._policy(lock=True)
        if current_version != (policy.version if policy else 0):
            raise ConflictError(message="自动换班策略已变化，请刷新")
        if policy is None:
            policy = AutoChangePolicy(
                college_id=self.cid,
                group_id=self.gid,
                semester_id=self.sid,
                authorizer_user_id=actor.id,
                enabled=False,
                version=0,
            )
            self.db.add(policy)
        if enabled and not policy.enabled:
            policy.request_cutoff_id = (
                self.db.scalar(select(func.max(AssignmentChangeRequest.id))) or 0
            )
            policy.enabled_at = utcnow()
        policy.version += 1
        policy.enabled, policy.authorizer_user_id = enabled, actor.id
        self.db.flush()
        result = self.policy_dto(policy)
        self.db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="assignment.auto_change.policy",
                resource_type="auto_change_policy",
                resource_id=str(policy.id),
                after_json=result,
            )
        )
        self.db.commit()
        return result

    def get_policy(self, actor):
        self._enabled()
        AssignmentPlanService(self.db, actor, self.cid, self.gid)._context(self.sid)
        resolve_scope(self.db, actor, self.cid, "assignment.change_review", write=True)
        return self.policy_dto(self._policy())

    def _source(self, request_id):
        row = self.db.execute(
            select(AssignmentChangeRequest, InspectionAssignment, InspectionTask)
            .join(
                InspectionAssignment,
                InspectionAssignment.id == AssignmentChangeRequest.assignment_id,
            )
            .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
            .where(
                AssignmentChangeRequest.id == request_id,
                InspectionTask.college_id == self.cid,
                InspectionTask.group_id == self.gid,
                InspectionTask.semester_id == self.sid,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            raise NotFoundError("换班申请不在当前范围")
        return row

    def register(self, request_id):
        """Flush-only event registration; called in the request creation transaction."""
        self._enabled()
        request, assignment, _ = self._source(request_id)
        policy = self._policy(lock=True)
        if (
            policy is None
            or not policy.enabled
            or request.id <= policy.request_cutoff_id
            or request.status != "PENDING"
            or assignment.revoked_at is not None
        ):
            return None
        existing = self.db.scalar(
            select(AutoChangeExecution).where(AutoChangeExecution.request_id == request.id)
        )
        if existing is not None:
            return existing
        execution = AutoChangeExecution(
            environment=get_settings().app_env,
            policy_id=policy.id,
            request_id=request.id,
            authorizer_user_id=policy.authorizer_user_id,
            policy_version=policy.version,
            status="QUEUED",
        )
        self.db.add(execution)
        self.db.flush()
        return execution

    def _authorizer(self, user_id):
        repo = IdentityRepository(self.db)
        user = repo.get_user_by_id(user_id)
        if user is None or user.status != "ACTIVE":
            raise PermissionDeniedError("策略授权人已停用")
        return CurrentUser(
            user.id,
            user.username,
            user.display_name,
            user.status,
            repo.list_effective_role_codes(user.id),
            repo.list_effective_permissions(user.id),
        )

    def _locked(self, execution_id):
        self._enabled()
        initial = self.db.get(AutoChangeExecution, execution_id)
        if initial is None:
            raise NotFoundError()
        actor = self._authorizer(initial.authorizer_user_id)
        plans = AssignmentPlanService(self.db, actor, self.cid, self.gid)
        plans._context(self.sid)
        review_scope = resolve_scope(
            self.db, actor, self.cid, "assignment.change_review", write=True
        )
        policy = self._policy(lock=True)
        execution = self.db.scalar(
            select(AutoChangeExecution)
            .where(AutoChangeExecution.id == execution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if policy is None or execution.policy_id != policy.id:
            raise NotFoundError()
        _, _, task = self._source(execution.request_id)
        if (
            self.db.scalar(
                select(InspectionTask.id).where(
                    InspectionTask.id == task.id, review_scope.task_condition()
                )
            )
            is None
        ):
            raise NotFoundError()
        if execution.status != "SUCCEEDED" and (
            not policy.enabled or policy.version != execution.policy_version
        ):
            raise ConflictError(message="自动换班策略已关闭或发生变化，请转人工处理")
        return plans, policy, execution

    @staticmethod
    def _result(execution):
        if execution.status == "SUCCEEDED":
            return execution.result_json
        return {
            "execution_id": str(execution.id),
            "status": execution.status,
            "reason_code": execution.reason_code,
            "plan_id": execution.plan_id,
            "revision": execution.plan_revision,
        }

    @atomic_write
    def prepare(self, execution_id):
        plans, _, execution = self._locked(execution_id)
        if execution.status != "QUEUED":
            self.db.commit()
            return self._result(execution)
        request, assignment, task = self._source(execution.request_id)
        if request.status != "PENDING" or assignment.revoked_at is not None:
            raise ConflictError(message="申请已处理或原受派已改变")
        scope, semester, _ = plans._context(self.sid)
        tasks = plans._targets(semester.id, [task.id])
        candidates = [
            uid
            for uid in plans.candidate_ids(semester, tasks)
            if uid != assignment.volunteer_user_id
        ]
        if len(candidates) > 500:
            raise ConflictError(message="候选范围超过单次处理上限")
        snapshot = load_snapshot(self.db, semester, tasks, candidates, lock_inputs=True)
        # Warnings require a person; they are never auto-confirmed by the Agent.
        safe_tasks = [
            replace(
                item,
                candidates=frozenset(
                    uid for uid in item.candidates if not snapshot.warnings.get((item.id, uid))
                ),
            )
            for item in snapshot.tasks
        ]
        settings = get_settings()
        result = plan_assignments(
            safe_tasks,
            snapshot.volunteers,
            day_cap=settings.assignment_max_tasks_per_day,
            week_cap=settings.assignment_max_tasks_per_week,
        )
        if task.id not in result.assignments:
            execution.status, execution.reason_code = "MANUAL_REQUIRED", "NO_SAFE_CANDIDATE"
        else:
            preview = plans.preview_in_transaction(
                {
                    "semester_id": str(self.sid),
                    "task_ids": [str(task.id)],
                    "assignments": {str(task.id): str(result.assignments[task.id])},
                    "reason": "系统按已授权策略自动换班",
                }
            )
            if any(item["warning_codes"] for item in preview["assigned"]):
                raise ConflictError(message="当前方案需要人工确认")
            execution.plan_id, execution.plan_revision = preview["id"], preview["revision"]
            execution.status = "PREPARED"
        self.db.commit()
        return self._result(execution)

    def _record_success(self, execution, result):
        execution.status, execution.reason_code, execution.result_json = "SUCCEEDED", None, result
        self.db.flush()

    @atomic_write
    def apply(self, execution_id):
        plans, policy, execution = self._locked(execution_id)
        if execution.status == "SUCCEEDED":
            self.db.commit()
            return execution.result_json
        if execution.status != "PREPARED":
            raise ConflictError(message="换班方案尚未就绪或需人工处理")
        request, old, task = self._source(execution.request_id)
        result = plans.commit_in_transaction(
            execution.plan_id,
            {
                "revision": execution.plan_revision,
                "confirmations": [],
            },
            automation=AutoChangeOrigin(
                str(execution.id),
                str(request.id),
                str(policy.id),
                execution.policy_version,
                str(execution.authorizer_user_id),
            ),
        )
        new = self.db.scalar(
            select(InspectionAssignment)
            .where(
                InspectionAssignment.task_id == task.id, InspectionAssignment.revoked_at.is_(None)
            )
            .execution_options(populate_existing=True)
        )
        receipt = {
            "status": "SUCCEEDED",
            "execution_id": str(execution.id),
            "request_id": str(request.id),
            "old_assignment_id": str(old.id),
            "new_assignment_id": str(new.id),
            "volunteer_user_id": str(new.volunteer_user_id),
            "plan_result": result,
        }
        self._record_success(execution, receipt)
        self.db.commit()
        return receipt
