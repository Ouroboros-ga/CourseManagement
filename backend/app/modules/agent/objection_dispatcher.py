"""Precheck-specific source/receipt rules over the shared durable ADP lifecycle."""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.agent.adp_client import AdpCallError, AdpWorkflowClient
from app.modules.agent.change_dispatcher import ChangeDispatcher, DispatchService
from app.modules.agent.models import AgentRun
from app.modules.agent.objection_runtime import service_for_job
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.precheck_schemas import PrecheckResult
from app.modules.objection.precheck_service import ObjectionPrecheckService


class ObjectionDispatchService(DispatchService):
    source_model = ObjectionPrecheckJob
    source_fk = "objection_precheck_job_id"
    workflow_kind = "objection"
    pending_states = ("QUEUED",)

    def _source_college(self, execution_id):
        job = self.db.get(ObjectionPrecheckJob, execution_id)
        if job is None or job.environment != self.environment:
            raise NotFoundError()
        return job.college_id

    def _prepare_source(self, execution_id):
        service = service_for_job(self.db, execution_id)
        job, row = service._execution(execution_id)
        if job.status == "QUEUED":
            if service.begin_in_transaction(job.id) is None:
                raise ConflictError(message="申诉资料已变化")
        else:
            service._assert_attempt(job, job.attempt_token)
            if not service._current(job, row, lock_files=True):
                raise ConflictError(message="申诉资料已变化")
        return job

    def _issue_run(self, runs, execution_id):
        return runs.issue_objection(self.app_key_id, execution_id)

    def _outcome(self, execution):
        if execution.status in {"FAILED", "STALE"}:
            return "MANUAL_REQUIRED"
        if execution.status != "SUCCEEDED":
            return None
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.objection_precheck_job_id == execution.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None or run.status != "COMPLETED" or not execution.result_json:
            return "UNKNOWN"
        try:
            PrecheckResult.model_validate(execution.result_json)
        except ValueError:
            return "UNKNOWN"
        return "SUCCEEDED"

    def _set_manual(self, execution, reason):
        if execution.status == "SUCCEEDED":
            return
        if reason == "SOURCE_NO_LONGER_VALID":
            service = ObjectionPrecheckService(self.db, execution.college_id)
            try:
                current = service._current(execution, service._source(execution.objection_id))
            except NotFoundError:
                current = False
            if not current:
                execution.status, execution.error_code = "STALE", "SOURCE_CHANGED"
        if execution.status != "STALE":
            execution.status, execution.error_code = "FAILED", reason
        execution.attempt_token = None

    def _on_uncertain(self, execution, reason):
        self._set_manual(execution, reason)


class ObjectionDispatcher(ChangeDispatcher):
    workflow_kind = "objection"
    service_class = ObjectionDispatchService
    feature_flag = "agent_objection_precheck_enabled"

    def configured_application(self):
        config = get_settings().agent_adp_config
        return (
            super().configured_application()
            and getattr(self.client.config, "proof_delivery_verified", False)
            and (config is None or config.app_id != self.client.config.app_id)
        )

    def _start_remote(self, claim):
        return self.client.start_objection(claim.run_token, caller_ref=f"run-{claim.run_id}")


def main():
    import argparse
    import json
    import logging
    import time

    from app.core.database import get_session_factory
    from app.modules.agent.models import AgentWorkflowRun

    parser = argparse.ArgumentParser(description="Single-worker ADP objection dispatch/observation")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--observe-run", type=int)
    args = parser.parse_args()
    settings = get_settings()
    if args.observe_run is not None and args.observe_run <= 0:
        parser.error("run id must be positive")
    if args.observe_run is None and not (
        settings.agent_worker_enabled
        and settings.agent_objection_precheck_enabled
        and settings.agent_tools_enabled
        and settings.agent_adp_enabled
    ):
        raise SystemExit("ADP objection worker is disabled")
    try:
        client = AdpWorkflowClient.from_settings(settings, workflow_kind="objection")
    except AdpCallError as error:
        raise SystemExit(error.code) from None
    worker = ObjectionDispatcher(
        get_session_factory(),
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=settings.agent_objection_app_key_id,
        client=client,
        **settings.agent_adp_dispatch_limits.model_dump(),
    )
    if args.observe_run is None and (
        not worker.configured_application() or not client.config.header_binding_verified
    ):
        raise SystemExit(
            "Precheck requires independent application and verified Header/material delivery"
        )
    if args.observe_run is not None:
        worker.observe_once(args.observe_run)
        with worker.factory() as db:
            row = db.get(AgentWorkflowRun, args.observe_run)
            print(
                json.dumps(
                    {
                        "run_id": str(row.run_id),
                        "state": row.state,
                        "outcome": row.outcome,
                        "remote_status": row.remote_status,
                        "error_code": row.error_code,
                    }
                )
            )
        return
    try:
        while True:
            try:
                worked = worker.run_once()
            except Exception:
                logging.getLogger(__name__).error("adp_precheck_cycle_failed")
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
