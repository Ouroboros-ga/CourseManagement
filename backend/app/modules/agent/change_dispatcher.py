"""Single-worker cloud dispatch, durable observation and business-receipt reconciliation."""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.modules.agent.adp_client import AdpCallError, AdpWorkflowClient
from app.modules.agent.adp_schemas import AdpDispatchLimits
from app.modules.agent.change_runtime import service_for_execution
from app.modules.agent.models import AgentRun, AgentWorkflowRun
from app.modules.agent.run_context import RunService
from app.modules.inspection.automation_models import AutoChangeExecution
from app.modules.inspection.models import AssignmentChangeRequest, InspectionAssignment
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.organization.models import College
from app.modules.organization.service import atomic_write


@dataclass(frozen=True)
class DispatchClaim:
    run_id: int
    attempt_token: str
    run_token: str | None = field(default=None, repr=False)
    remote_run_id: str | None = None
    observation_state: str | None = None


class DispatchService:
    source_model: type[AutoChangeExecution] | type[ObjectionPrecheckJob] = AutoChangeExecution
    source_fk = "auto_change_execution_id"
    workflow_kind = "change"
    pending_states: tuple[str, ...] = ("QUEUED", "PREPARED")

    def __init__(
        self,
        db,
        connections,
        *,
        environment,
        app_key_id,
        config,
        max_active=5,
        poll_interval=2,
        wait_seconds=300,
        max_polls=100,
    ):
        self.db, self.connections, self.environment = db, connections, environment
        self.app_key_id, self.config = app_key_id, config
        limits = AdpDispatchLimits(
            max_active=max_active,
            poll_interval=poll_interval,
            wait_seconds=wait_seconds,
            max_polls=max_polls,
        )
        self.max_active, self.poll_interval = limits.max_active, limits.poll_interval
        self.wait_seconds, self.max_polls = limits.wait_seconds, limits.max_polls
        self.changed = False

    def _runtime_conditions(self):
        return (
            AgentRun.environment == self.environment,
            AgentRun.app_key_id == self.app_key_id,
            AgentRun.workflow_kind == self.workflow_kind,
        )

    def _source_college(self, execution_id):
        service, _ = service_for_execution(self.db, execution_id)
        return service.cid

    def _prepare_source(self, execution_id):
        service, _ = service_for_execution(self.db, execution_id)
        _, _, execution = service._locked(execution_id)
        request, assignment, _ = service._source(execution.request_id)
        if request.status != "PENDING" or assignment.revoked_at is not None:
            raise ConflictError(message="源申请已由其他流程处理")
        return execution

    def _issue_run(self, runs, execution_id):
        return runs.issue_change(self.app_key_id, execution_id)

    def _set_manual(self, execution, reason):
        execution.status, execution.reason_code = "MANUAL_REQUIRED", reason

    def _on_uncertain(self, execution, reason):
        pass

    def _cloud_ids(self):
        return (
            select(AgentWorkflowRun.run_id)
            .join(AgentRun, AgentRun.id == AgentWorkflowRun.run_id)
            .where(*self._runtime_conditions())
        )

    def _locked(self, run_id):
        initial = self.db.get(AgentRun, run_id)
        if initial is None or getattr(initial, self.source_fk) is None:
            raise NotFoundError()
        if initial.environment != self.environment or initial.app_key_id != self.app_key_id:
            raise NotFoundError()
        # Observation still records outcomes after permissions/policies are revoked.
        # The college lock serializes this with domain writes without granting any write action.
        self.db.scalar(select(College).where(College.id == initial.college_id).with_for_update())
        execution = self.db.scalar(
            select(self.source_model)
            .where(self.source_model.id == getattr(initial, self.source_fk))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        cloud = self.db.scalar(
            select(AgentWorkflowRun)
            .where(AgentWorkflowRun.run_id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if execution is None or cloud is None:
            raise NotFoundError()
        return run, execution, cloud

    def _matches_config(self, cloud):
        return (cloud.app_id, cloud.domain, cloud.region) == (
            self.config.app_id,
            self.config.domain,
            self.config.region,
        )

    def _outcome(self, execution):
        if execution.status == "MANUAL_REQUIRED":
            return "MANUAL_REQUIRED"
        if execution.status != "SUCCEEDED":
            return None
        receipt = execution.result_json or {}
        try:
            request = self._current_row(AssignmentChangeRequest, execution.request_id)
            old = self._current_row(InspectionAssignment, int(receipt["old_assignment_id"]))
            new = self._current_row(InspectionAssignment, int(receipt["new_assignment_id"]))
            if (
                receipt["status"] == "SUCCEEDED"
                and receipt["execution_id"] == str(execution.id)
                and receipt["request_id"] == str(request.id)
                and request.status == "APPROVED"
                and request.assignment_id == old.id
                and old.revoked_at is not None
                and new.id != old.id
                and new.task_id == old.task_id
                and new.volunteer_user_id == int(receipt["volunteer_user_id"])
                and new.assigned_by is None
                and new.assign_method == "AUTO"
            ):
                return "SUCCEEDED"
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
        return "UNKNOWN"

    def _current_row(self, model, row_id):
        # Domain observation already holds the college lock. Use current reads rather
        # than cached ORM values or an older MySQL REPEATABLE READ snapshot.
        return self.db.scalar(
            select(model)
            .where(model.id == row_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _finish(self, run, execution, cloud, *, state="FINISHED", error=None):
        cloud.outcome = self._outcome(execution)
        if cloud.outcome is None:
            cloud.outcome = "MANUAL_REQUIRED"
            self._set_manual(execution, error or "NO_COMMIT_RECEIPT")
        cloud.state, cloud.error_code = state, error
        if cloud.outcome == "UNKNOWN":
            cloud.error_code = error or "LOCAL_RECEIPT_INVALID"
        cloud.lease_until = cloud.next_poll_at = None
        run.revoked_at = run.revoked_at or utcnow()

    def _uncertain(self, run, execution, cloud, error):
        cloud.state, cloud.error_code = "UNCERTAIN", error
        cloud.outcome = self._outcome(execution) or "UNKNOWN"
        cloud.lease_until = cloud.next_poll_at = None
        run.revoked_at = run.revoked_at or utcnow()
        self._on_uncertain(execution, error)

    def _mark_source_manual(self, execution_id):
        self.db.rollback()
        college_id = self._source_college(execution_id)
        if college_id is not None:
            self.db.scalar(select(College).where(College.id == college_id).with_for_update())
        execution = self.db.scalar(
            select(self.source_model)
            .where(self.source_model.id == execution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if execution.status in self.pending_states or execution.status == "RUNNING":
            self._set_manual(execution, "SOURCE_NO_LONGER_VALID")
        run = self.db.scalar(
            select(AgentRun)
            .where(getattr(AgentRun, self.source_fk) == execution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        cloud = self.db.get(AgentWorkflowRun, run.id) if run else None
        if run is not None and (
            run.environment != self.environment or run.app_key_id != self.app_key_id
        ):
            self.db.rollback()
            return
        if cloud is not None:
            state = "OBSERVATION_FAILED" if cloud.remote_run_id is not None else "FINISHED"
            self._finish(run, execution, cloud, state=state, error="SOURCE_NO_LONGER_VALID")
        elif run is not None:
            run.revoked_at = run.revoked_at or utcnow()
        self.db.commit()
        self.changed = True

    @atomic_write
    def reserve_start(self):
        now = utcnow()
        retry_run = self.db.scalar(
            self._cloud_ids()
            .where(AgentWorkflowRun.state == "RETRY_WAIT", AgentWorkflowRun.next_poll_at <= now)
            .order_by(AgentWorkflowRun.next_poll_at)
            .limit(1)
        )
        if retry_run is not None:
            run, execution, cloud = self._locked(retry_run)
            if cloud.state != "RETRY_WAIT" or cloud.next_poll_at > now:
                self.db.rollback()
                return None
            if cloud.deadline_at <= now or not self._matches_config(cloud):
                self._finish(run, execution, cloud, error="DISPATCH_CONFIGURATION_OR_DEADLINE")
                self.db.commit()
                self.changed = True
                return None
            execution_id = execution.id
        else:
            active = self.db.scalar(
                select(func.count())
                .select_from(AgentWorkflowRun)
                .join(AgentRun, AgentRun.id == AgentWorkflowRun.run_id)
                .where(
                    *self._runtime_conditions(),
                    AgentWorkflowRun.state.in_(
                        [
                            "STARTING",
                            "WAITING",
                            "POLLING",
                            "RETRY_WAIT",
                            "UNCERTAIN",
                            "TIMED_OUT",
                            "OBSERVATION_FAILED",
                        ]
                    ),
                )
            )
            if active >= self.max_active:
                self.db.rollback()
                return None
            associated = (
                select(AgentWorkflowRun.run_id)
                .join(AgentRun, AgentRun.id == AgentWorkflowRun.run_id)
                .where(getattr(AgentRun, self.source_fk) == self.source_model.id)
                .exists()
            )
            execution_id = self.db.scalar(
                select(self.source_model.id)
                .where(
                    self.source_model.environment == self.environment,
                    self.source_model.status.in_(self.pending_states),
                    ~associated,
                    ~select(AgentRun.id)
                    .where(
                        getattr(AgentRun, self.source_fk) == self.source_model.id,
                        or_(
                            AgentRun.app_key_id != self.app_key_id,
                            AgentRun.environment != self.environment,
                        ),
                    )
                    .exists(),
                )
                .order_by(self.source_model.id)
                .limit(1)
            )
            if execution_id is None:
                self.db.rollback()
                return None
        try:
            execution = self._prepare_source(execution_id)
            existing_run = self.db.scalar(
                select(AgentRun)
                .where(getattr(AgentRun, self.source_fk) == execution_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            existing = (
                self.db.scalar(
                    select(AgentWorkflowRun)
                    .where(AgentWorkflowRun.run_id == existing_run.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if existing_run
                else None
            )
            if existing is not None and existing.state != "RETRY_WAIT":
                self.db.rollback()
                return None
            runs = RunService(self.db, self.connections, environment=self.environment)
            run, token = self._issue_run(runs, execution_id)
        except AppError:
            self._mark_source_manual(execution_id)
            return None
        if existing is None:
            existing = AgentWorkflowRun(
                run_id=run.id,
                app_id=self.config.app_id,
                domain=self.config.domain,
                region=self.config.region,
                deadline_at=now + timedelta(seconds=self.wait_seconds),
                create_attempts=0,
                poll_count=0,
            )
            self.db.add(existing)
        existing.state, existing.attempt_token = "STARTING", uuid4().hex
        existing.create_attempts += 1
        existing.lease_until = now + timedelta(seconds=60)
        existing.next_poll_at = None
        run.credential_expires_at = min(run.credential_expires_at, existing.deadline_at)
        self.db.commit()
        self.changed = True
        return DispatchClaim(run.id, existing.attempt_token, token)

    @atomic_write
    def record_start(self, claim, response=None, error=None):
        run, execution, cloud = self._locked(claim.run_id)
        if cloud.attempt_token != claim.attempt_token or cloud.state not in {
            "STARTING",
            "UNCERTAIN",
        }:
            self.db.rollback()
            return False
        now = utcnow()
        if response is not None:
            if cloud.state == "STARTING" and cloud.lease_until <= now:
                self._uncertain(run, execution, cloud, "START_ACK_LATE")
            cloud.remote_run_id, cloud.request_id = response.workflow_run_id, response.request_id
            cloud.state, cloud.next_poll_at, cloud.lease_until = "WAITING", now, None
        elif error.ambiguous:
            self._uncertain(run, execution, cloud, error.code)
        elif error.retryable and cloud.create_attempts < 3 and cloud.deadline_at > now:
            cloud.state, cloud.error_code = "RETRY_WAIT", error.code
            cloud.next_poll_at = now + timedelta(seconds=2**cloud.create_attempts)
            cloud.lease_until = None
        else:
            self._finish(run, execution, cloud, error=error.code)
        self.db.commit()
        return True

    @atomic_write
    def recover_start(self):
        run_id = self.db.scalar(
            self._cloud_ids()
            .where(AgentWorkflowRun.state == "STARTING", AgentWorkflowRun.lease_until <= utcnow())
            .order_by(AgentWorkflowRun.lease_until)
            .limit(1)
        )
        if run_id is None:
            self.db.rollback()
            return False
        run, execution, cloud = self._locked(run_id)
        if cloud.state != "STARTING" or cloud.lease_until > utcnow():
            self.db.rollback()
            return False
        self._uncertain(run, execution, cloud, "START_LEASE_EXPIRED")
        self.db.commit()
        return True

    @atomic_write
    def reserve_poll(self):
        now = utcnow()
        run_id = self.db.scalar(
            self._cloud_ids()
            .where(
                or_(
                    (AgentWorkflowRun.state == "WAITING") & (AgentWorkflowRun.next_poll_at <= now),
                    (AgentWorkflowRun.state == "POLLING") & (AgentWorkflowRun.lease_until <= now),
                )
            )
            .order_by(AgentWorkflowRun.next_poll_at, AgentWorkflowRun.run_id)
            .limit(1)
        )
        if run_id is None:
            self.db.rollback()
            return None
        run, execution, cloud = self._locked(run_id)
        eligible = (cloud.state == "WAITING" and cloud.next_poll_at <= now) or (
            cloud.state == "POLLING" and cloud.lease_until <= now
        )
        if not eligible:
            self.db.rollback()
            return None
        if cloud.deadline_at <= now or cloud.poll_count >= self.max_polls:
            self._finish(run, execution, cloud, state="TIMED_OUT", error="REMOTE_WAIT_EXPIRED")
        elif not self._matches_config(cloud):
            self._finish(
                run,
                execution,
                cloud,
                state="OBSERVATION_FAILED",
                error="CLOUD_CONFIGURATION_CHANGED",
            )
        else:
            cloud.state, cloud.attempt_token = "POLLING", uuid4().hex
            cloud.lease_until = now + timedelta(seconds=60)
            cloud.poll_count += 1
            claim = DispatchClaim(run.id, cloud.attempt_token, remote_run_id=cloud.remote_run_id)
            self.db.commit()
            return claim
        self.db.commit()
        self.changed = True
        return None

    @atomic_write
    def reserve_observation(self, run_id):
        run, execution, cloud = self._locked(run_id)
        if cloud.state == "FINISHED":
            self.db.rollback()
            return None
        if cloud.state not in {"TIMED_OUT", "OBSERVATION_FAILED", "UNCERTAIN"}:
            raise ConflictError(message="该运行仍在正常追踪，请等待后台处理")
        if cloud.remote_run_id is None:
            raise ConflictError(message="没有已确认的云端实例编号，需先在云端人工核查")
        if not self._matches_config(cloud):
            raise ConflictError(message="请使用该运行原有的云端应用与环境配置复查")
        previous = cloud.state
        cloud.state, cloud.attempt_token = "POLLING", uuid4().hex
        cloud.lease_until = utcnow() + timedelta(seconds=60)
        cloud.poll_count += 1
        run.revoked_at = run.revoked_at or utcnow()
        claim = DispatchClaim(
            run_id,
            cloud.attempt_token,
            remote_run_id=cloud.remote_run_id,
            observation_state=previous,
        )
        self.db.commit()
        return claim

    @atomic_write
    def record_poll(self, claim, snapshot=None, error=None):
        run, execution, cloud = self._locked(claim.run_id)
        if (
            cloud.state != "POLLING"
            or cloud.attempt_token != claim.attempt_token
            or cloud.lease_until <= utcnow()
        ):
            self.db.rollback()
            return False
        if snapshot is not None:
            if snapshot.workflow_run_id != cloud.remote_run_id:
                raise ConflictError(message="云端实例与派发记录不一致")
            cloud.remote_status, cloud.request_id = snapshot.status, snapshot.request_id
            if snapshot.terminal:
                outcome = self._outcome(execution)
                reason = (
                    (
                        "CLOUD_SUCCEEDED_WITHOUT_RECEIPT"
                        if snapshot.status == "SUCCEEDED"
                        else "CLOUD_TERMINAL_WITHOUT_RECEIPT"
                    )
                    if outcome is None
                    else None
                )
                self._finish(run, execution, cloud, error=reason)
            else:
                if claim.observation_state:
                    self._finish(
                        run,
                        execution,
                        cloud,
                        state=claim.observation_state,
                        error="REMOTE_STILL_ACTIVE",
                    )
                else:
                    cloud.state, cloud.lease_until = "WAITING", None
                    cloud.next_poll_at = utcnow() + timedelta(seconds=self.poll_interval)
        elif error.retryable and not claim.observation_state:
            cloud.state, cloud.error_code, cloud.lease_until = "WAITING", error.code, None
            cloud.next_poll_at = utcnow() + timedelta(seconds=self.poll_interval)
        else:
            self._finish(
                run,
                execution,
                cloud,
                state=claim.observation_state or "OBSERVATION_FAILED",
                error=error.code,
            )
        self.db.commit()
        return True


class ChangeDispatcher:
    workflow_kind = "change"
    service_class = DispatchService
    feature_flag = "agent_auto_change_enabled"

    def __init__(self, session_factory, connections, *, environment, app_key_id, client, **limits):
        self.factory, self.connections = session_factory, connections
        self.environment, self.app_key_id, self.client = environment, app_key_id, client
        self.limits = limits

    def _service(self, db):
        return self.service_class(
            db,
            self.connections,
            environment=self.environment,
            app_key_id=self.app_key_id,
            config=self.client.config,
            **self.limits,
        )

    def configured_application(self):
        return getattr(
            self.client, "workflow_kind", self.workflow_kind
        ) == self.workflow_kind and any(
            connection.app_key_id == self.app_key_id
            and connection.environment == self.environment
            and connection.entry_kind == "AUTOMATION"
            and connection.workflow_kind == self.workflow_kind
            for connection in self.connections
        )

    def run_once(self):
        settings = get_settings()
        if not (
            settings.agent_adp_enabled
            and getattr(settings, self.feature_flag)
            and settings.agent_tools_enabled
            and self.client.config.header_binding_verified
            and self.configured_application()
        ):
            return False
        with self.factory() as db:
            service = self._service(db)
            if service.recover_start():
                return True
            claim = service.reserve_poll()
            if claim is None and service.changed:
                return True
            polling = claim is not None
            if claim is None:
                claim = service.reserve_start()
                if claim is None:
                    return service.changed
        response, error = None, None
        try:
            response = (
                self.client.describe(claim.remote_run_id) if polling else self._start_remote(claim)
            )
        except AdpCallError as failure:
            error = failure
        except Exception:
            error = AdpCallError("UPSTREAM_UNCERTAIN", ambiguous=not polling, retryable=polling)
        with self.factory() as db:
            service = self._service(db)
            if polling:
                service.record_poll(claim, response, error)
            else:
                service.record_start(claim, response, error)
        return True

    def _start_remote(self, claim):
        return self.client.start_change(claim.run_token, caller_ref=f"run-{claim.run_id}")

    def observe_once(self, run_id):
        if not get_settings().agent_adp_enabled:
            return False
        with self.factory() as db:
            claim = self._service(db).reserve_observation(run_id)
        if claim is None:
            return False
        snapshot, error = None, None
        try:
            snapshot = self.client.describe(claim.remote_run_id)
        except AdpCallError as failure:
            error = failure
        except Exception:
            error = AdpCallError("UPSTREAM_UNCERTAIN", retryable=True)
        with self.factory() as db:
            return self._service(db).record_poll(claim, snapshot, error)


def main():
    import argparse
    import logging
    import time

    from app.core.database import get_session_factory

    parser = argparse.ArgumentParser(description="Single-worker ADP change dispatch/observation")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--observe-run", type=int)
    args = parser.parse_args()
    settings = get_settings()
    if args.observe_run is not None and args.observe_run <= 0:
        parser.error("run id must be positive")
    if args.observe_run is None and not (
        settings.agent_worker_enabled
        and settings.agent_auto_change_enabled
        and settings.agent_tools_enabled
        and settings.agent_adp_enabled
    ):
        raise SystemExit("ADP change worker is disabled")
    try:
        client = AdpWorkflowClient.from_settings(settings)
    except AdpCallError as error:
        raise SystemExit(error.code) from None
    if args.observe_run is None and (
        not client.config.header_binding_verified or not settings.agent_change_app_key_id
    ):
        raise SystemExit("ADP dispatch requires verified Header binding and an application key id")
    worker = ChangeDispatcher(
        get_session_factory(),
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=settings.agent_change_app_key_id,
        client=client,
        **settings.agent_adp_dispatch_limits.model_dump(),
    )
    if args.observe_run is None and not worker.configured_application():
        raise SystemExit("ADP change tool application is not configured for this environment")
    try:
        if args.observe_run is not None:
            worker.observe_once(args.observe_run)
            import json

            with worker.factory() as db:
                row = db.get(AgentWorkflowRun, args.observe_run)
                print(
                    json.dumps(
                        {
                            "run_id": str(args.observe_run),
                            "state": row.state,
                            "outcome": row.outcome,
                            "remote_status": row.remote_status,
                            "error_code": row.error_code,
                        }
                    )
                )
            return
        while True:
            try:
                worked = worker.run_once()
            except Exception:
                # Keep raw SDK/SQL inputs out of logs. STARTING rows recover as uncertain.
                logging.getLogger(__name__).error("adp_dispatch_cycle_failed")
                if args.once:
                    raise SystemExit("Dispatch failed; inspect durable tracking state") from None
                worked = False
            if args.once:
                return
            if not worked:
                time.sleep(0.5)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
