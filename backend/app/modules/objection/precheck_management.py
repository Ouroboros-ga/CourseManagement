"""Management facade: reuse actual roles/scopes and retain every precheck attempt."""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.agent.models import AgentRun, AgentWorkflowRun
from app.modules.audit.models import AuditLog
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.models import InspectionTask
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.precheck_service import ObjectionPrecheckService
from app.modules.organization.service import atomic_write

RETRY_MESSAGES = {
    "NO_RETRY_PERMISSION": "当前账号无权重新发起预审",
    "OBJECTION_CLOSED": "申诉已完成或考勤已撤回",
    "SEMESTER_ARCHIVED": "该学期已归档，不能重新发起预审",
    "PRECHECK_ALREADY_ACTIVE_OR_COMPLETE": "已有进行中或有效的预审记录",
    "UNTRACKED_EXECUTION": "旧预审缺少可核对的执行记录，请联系系统管理员处理",
    "CLOUD_NOT_TERMINAL": "上一轮预审尚未确认结束，请先核查运行记录",
    "POLICY_UNAVAILABLE": "请先由学院管理员开启预审策略",
    "CONFIGURATION_NOT_READY": "预审接入配置尚未就绪，请先完成后台配置",
}


class PrecheckManagementService:
    def __init__(self, db, college_id):
        self.db, self.cid = db, college_id
        self.domain = ObjectionPrecheckService(db, college_id)

    @staticmethod
    def configuration_ready():
        settings = get_settings()
        config = settings.agent_adp_objection_config
        return bool(
            settings.agent_tools_enabled
            and settings.agent_worker_enabled
            and settings.agent_adp_enabled
            and config is not None
            and config.header_binding_verified
            and config.proof_delivery_verified
            and (
                settings.agent_adp_config is None
                or settings.agent_adp_config.app_id != config.app_id
            )
            and any(
                c.app_key_id == settings.agent_objection_app_key_id
                and c.environment == settings.app_env
                and c.entry_kind == "AUTOMATION"
                and c.workflow_kind == "objection"
                for c in settings.agent_tool_connections
            )
        )

    def policy(self, actor):
        self.domain._enabled()
        self.domain._policy_authority(actor, write=False)
        policy = self.domain._policy()
        return {
            "enabled": policy.enabled if policy else False,
            "version": policy.version if policy else 0,
            "configuration_ready": self.configuration_ready(),
        }

    @atomic_write
    def update_policy(self, actor, *, enabled, current_version):
        self.domain._enabled()
        self.domain._policy_authority(actor)
        if enabled and not self.configuration_ready():
            raise ConflictError(message="预审接入配置尚未就绪，请先完成后台配置")
        self.domain.set_policy(actor, enabled=enabled, current_version=current_version)
        return self.policy(actor)

    def _retry_scope(self, actor, *, write=False):
        actual = self.domain._actor(actor.id)
        if not {"SUPER_ADMIN", "TEACHER_ADMIN"}.intersection(actual.roles):
            raise PermissionDeniedError("仅教务管理员可重新发起预审")
        return resolve_scope(self.db, actual, self.cid, "objection.final_review", write=write)

    def _case(self, objection_id, scope, *, lock=False):
        row = self.domain._open_source(objection_id) if lock else self.domain._source(objection_id)
        if (
            self.db.scalar(
                select(InspectionTask.id).where(
                    InspectionTask.id == row[2].id, scope.task_condition()
                )
            )
            is None
        ):
            raise NotFoundError()
        return row

    def _latest(self, objection_id, *, lock=False):
        statement = (
            select(ObjectionPrecheckJob)
            .where(
                ObjectionPrecheckJob.objection_id == objection_id,
                ObjectionPrecheckJob.environment == get_settings().app_env,
                ObjectionPrecheckJob.college_id == self.cid,
            )
            .order_by(ObjectionPrecheckJob.id.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement.execution_options(populate_existing=True))

    def _cloud_problem(self, job, *, lock=False):
        if job is None:
            return None
        query = select(AgentRun).where(AgentRun.objection_precheck_job_id == job.id)
        if lock:
            query = query.with_for_update()
        run = self.db.scalar(query.execution_options(populate_existing=True))
        if run is None:
            return "UNTRACKED_EXECUTION" if job.status == "RUNNING" else None
        query = select(AgentWorkflowRun).where(AgentWorkflowRun.run_id == run.id)
        if lock:
            query = query.with_for_update()
        cloud = self.db.scalar(query.execution_options(populate_existing=True))
        if cloud is None:
            return "UNTRACKED_EXECUTION"
        if cloud.state != "FINISHED":
            return "CLOUD_NOT_TERMINAL"
        return None

    def _problem(self, actor, row, job, *, current, scope=None):
        if scope is None:
            try:
                scope = self._retry_scope(actor)
                self._case(row[0].id, scope)
            except (PermissionDeniedError, NotFoundError):
                return "NO_RETRY_PERMISSION"
            lock_cloud = False
        else:
            lock_cloud = True
        if row[0].final_status != "PENDING" or row[1].effect_state != "EFFECTIVE":
            return "OBJECTION_CLOSED"
        if (
            self.db.scalar(select(Semester.status).where(Semester.id == row[2].semester_id))
            == "ARCHIVED"
        ):
            return "SEMESTER_ARCHIVED"
        if job is not None and current and job.status in {"QUEUED", "RUNNING", "SUCCEEDED"}:
            return "PRECHECK_ALREADY_ACTIVE_OR_COMPLETE"
        blocked = self._cloud_problem(job, lock=lock_cloud)
        if blocked:
            return blocked
        policy = self.domain._policy()
        if policy is None or not policy.enabled:
            return "POLICY_UNAVAILABLE"
        if not self.configuration_ready():
            return "CONFIGURATION_NOT_READY"
        return None

    def _view(self, actor, row, job):
        from app.modules.objection.precheck_review import review_options

        current = job is not None and self.domain._current(job, row)
        problem = self._problem(actor, row, job, current=current)
        return {
            "objection_id": str(row[0].id),
            "final_status": row[0].final_status,
            "job_id": str(job.id) if job else None,
            "status": "NOT_STARTED" if job is None else job.status if current else "STALE",
            "stored_status": job.status if job else None,
            "is_current": current,
            "error_code": job.error_code if job and current else "SOURCE_CHANGED" if job else None,
            "result": job.result_json if job and current and job.status == "SUCCEEDED" else None,
            "attempt_no": job.attempt_no if job else 0,
            "can_retry": problem is None,
            "retry_block_reason": problem,
            "retry_block_message": RETRY_MESSAGES.get(problem) if problem else None,
            "created_at": job.created_at if job else None,
            "updated_at": job.updated_at if job else None,
            **review_options(self.domain, actor, row, job),
        }

    def latest(self, actor, objection_id):
        self.domain._enabled()
        scope = resolve_scope(self.db, actor, self.cid, "objection.read")
        row = self._case(objection_id, scope)
        return self._view(actor, row, self._latest(objection_id))

    @atomic_write
    def retry(self, actor, objection_id, *, expected_job_id, request_id):
        self.domain._enabled()
        scope = self._retry_scope(actor, write=True)
        policy = self.domain._policy(lock=True)
        row = self._case(objection_id, scope, lock=True)
        if row[0].final_status != "PENDING" or row[1].effect_state != "EFFECTIVE":
            raise ConflictError(message="申诉已完成或考勤已撤回")
        latest = self._latest(objection_id, lock=True)
        digest = self.domain._snapshot(row, lock_files=True)[0]
        if latest and expected_job_id != latest.id:
            if expected_job_id is None or latest.retry_of_job_id == expected_job_id:
                return self._view(actor, row, latest)
            raise ConflictError(message="预审记录已变化，请刷新")
        if latest is None and expected_job_id is not None:
            raise ConflictError(message="预审记录已变化，请刷新")
        if (
            latest
            and latest.source_digest == digest
            and latest.status in {"QUEUED", "RUNNING", "SUCCEEDED"}
        ):
            return self._view(actor, row, latest)
        problem = self._problem(
            actor,
            row,
            latest,
            current=latest is not None and latest.source_digest == digest,
            scope=scope,
        )
        if problem:
            raise ConflictError(message=RETRY_MESSAGES[problem])
        group_last = self.db.scalar(
            select(ObjectionPrecheckJob)
            .where(
                ObjectionPrecheckJob.objection_id == objection_id,
                ObjectionPrecheckJob.source_digest == digest,
                ObjectionPrecheckJob.policy_version == policy.version,
                ObjectionPrecheckJob.environment == get_settings().app_env,
            )
            .order_by(ObjectionPrecheckJob.attempt_no.desc())
            .limit(1)
            .with_for_update()
        )
        new = self.domain._create_job(
            row,
            actor.id,
            policy,
            digest,
            attempt_no=(group_last.attempt_no + 1 if group_last else 1),
            retry_of=latest.id if latest else None,
        )
        if latest and latest.source_digest != digest and latest.status == "QUEUED":
            latest.status, latest.error_code, latest.attempt_token = "STALE", "SOURCE_CHANGED", None
        if latest:
            old_run = self.db.scalar(
                select(AgentRun)
                .where(AgentRun.objection_precheck_job_id == latest.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if old_run:
                old_run.revoked_at = old_run.revoked_at or utcnow()
        self.db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="objection.precheck.retry",
                resource_type="objection_precheck_job",
                resource_id=str(new.id),
                request_id=request_id,
                after_json={
                    "college_id": str(self.cid),
                    "objection_id": str(objection_id),
                    "previous_job_id": str(latest.id) if latest else None,
                    "attempt_no": new.attempt_no,
                },
            )
        )
        self.db.commit()
        return self._view(actor, row, new)
