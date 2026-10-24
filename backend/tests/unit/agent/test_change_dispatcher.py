from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.modules.agent.adp_client import AdpCallError, AdpCreated, AdpSnapshot
from app.modules.agent.change_dispatcher import ChangeDispatcher, DispatchService
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.models import AgentRun, AgentWorkflowRun
from app.modules.agent.run_context import RunService
from app.modules.inspection.models import InspectionAssignment
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


class Cloud:
    def __init__(self):
        from tests.unit.agent.test_adp_client import config

        self.config = config()
        self.starts, self.polls = [], []
        self.failure, self.on_poll = None, None
        self.status = "RUNNING"

    def start_change(self, token, *, caller_ref):
        self.starts.append((token, caller_ref))
        if self.failure:
            raise self.failure
        return AdpCreated("wfr-durable-one", "req-1")

    def describe(self, run_id):
        self.polls.append(run_id)
        if self.on_poll:
            self.on_poll()
        return AdpSnapshot(run_id, self.status, "req-2")


@pytest.fixture
def prepared_dispatch(monkeypatch):
    from tests.unit.agent.test_change_runtime import bound, connection

    source = bound.__wrapped__(monkeypatch)
    db, auto, execution, old = next(source)
    monkeypatch.setattr(get_settings(), "agent_adp_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_tools_enabled", True)
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    cloud = Cloud()

    def worker():
        return ChangeDispatcher(
            factory, [connection()], environment="dev", app_key_id="change-app", client=cloud
        )

    try:
        yield db, auto, execution, old, cloud, worker, factory
    finally:
        source.close()


def force_poll(db):
    row = db.scalar(select(AgentWorkflowRun))
    row.next_poll_at = utcnow() - timedelta(seconds=1)
    db.commit()
    return row


def test_restart_polls_saved_instance_and_cloud_success_cannot_fabricate_reassignment(
    prepared_dispatch,
):
    db, _, _, old, cloud, worker, _ = prepared_dispatch
    assert worker().run_once()
    row = force_poll(db)
    assert row.state == "WAITING" and row.remote_run_id == "wfr-durable-one"
    cloud.status = "SUCCEEDED"
    assert worker().run_once()
    db.expire_all()
    assert db.get(AgentWorkflowRun, row.run_id).outcome == "MANUAL_REQUIRED"
    assert db.get(InspectionAssignment, old.id).revoked_at is None
    assert len(cloud.starts) == 1 and cloud.polls == ["wfr-durable-one"]


def test_business_receipt_wins_when_cloud_fails_after_real_reassignment(prepared_dispatch):
    from tests.unit.agent.test_change_runtime import connection

    db, _, _, old, cloud, worker, factory = prepared_dispatch
    worker().run_once()

    def actual_change():
        with factory() as session:
            runs = RunService(session, [connection()], environment="dev")
            context = runs.resolve("c" * 40, cloud.starts[0][0])
            invoke_tool(session, context, "change_prepare", {})
            invoke_tool(session, runs.resolve("c" * 40, cloud.starts[0][0]), "change_apply", {})

    cloud.on_poll, cloud.status = actual_change, "FAILED"
    row = force_poll(db)
    assert worker().run_once()
    db.expire_all()
    row = db.get(AgentWorkflowRun, row.run_id)
    assert row.outcome == "SUCCEEDED" and row.remote_status == "FAILED"
    assert db.get(InspectionAssignment, old.id).revoked_at is not None
    assert row.state == "FINISHED"


def test_receipt_reconciliation_refreshes_cached_assignment_facts(prepared_dispatch):
    from tests.unit.agent.test_change_runtime import connection

    db, _, execution, old, cloud, worker, factory = prepared_dispatch
    assert old.revoked_at is None
    worker().run_once()
    with factory() as session:
        runs = RunService(session, [connection()], environment="dev")
        context = runs.resolve("c" * 40, cloud.starts[0][0])
        invoke_tool(session, context, "change_prepare", {})
        invoke_tool(session, runs.resolve("c" * 40, cloud.starts[0][0]), "change_apply", {})
    db.refresh(execution)
    assert execution.status == "SUCCEEDED" and old.revoked_at is None
    assert worker()._service(db)._outcome(execution) == "SUCCEEDED"


def test_uncertain_create_is_persisted_and_not_repeated(prepared_dispatch):
    db, _, _, old, cloud, worker, _ = prepared_dispatch
    cloud.failure = AdpCallError("UPSTREAM_UNCERTAIN", ambiguous=True)
    assert worker().run_once()
    row = db.scalar(select(AgentWorkflowRun))
    assert row.state == "UNCERTAIN" and row.outcome == "UNKNOWN"
    assert db.get(AgentRun, row.run_id).revoked_at is not None
    assert worker().run_once() is False
    assert len(cloud.starts) == 1
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_crash_before_create_ack_never_restarts_cloud_creation(prepared_dispatch):
    from tests.unit.agent.test_change_runtime import connection

    db, _, _, _, cloud, worker, _ = prepared_dispatch
    service = DispatchService(
        db, [connection()], environment="dev", app_key_id="change-app", config=cloud.config
    )
    claim = service.reserve_start()
    row = db.get(AgentWorkflowRun, claim.run_id)
    row.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker().run_once()
    db.expire_all()
    assert db.get(AgentWorkflowRun, claim.run_id).state == "UNCERTAIN"
    assert cloud.starts == []


def test_expired_wait_revokes_writes_but_does_not_claim_cloud_cancellation(prepared_dispatch):
    db, _, _, old, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    row = force_poll(db)
    row.deadline_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker().run_once()
    db.expire_all()
    row = db.get(AgentWorkflowRun, row.run_id)
    assert row.state == "TIMED_OUT" and row.outcome == "MANUAL_REQUIRED"
    assert row.remote_status != "CANCELED" and cloud.polls == []
    assert db.get(AgentRun, row.run_id).revoked_at is not None
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_disabled_runtime_does_not_claim_any_source_request(prepared_dispatch, monkeypatch):
    db, _, _, _, cloud, worker, _ = prepared_dispatch
    monkeypatch.setattr(get_settings(), "agent_adp_enabled", False)
    assert worker().run_once() is False
    assert db.query(AgentWorkflowRun).count() == 0 and cloud.starts == []


def test_policy_disabled_during_rate_limit_backoff_closes_dispatch(prepared_dispatch):
    db, auto, execution, old, cloud, worker, _ = prepared_dispatch
    cloud.failure = AdpCallError("UPSTREAM_REJECTED", retryable=True)
    worker().run_once()
    row = force_poll(db)
    assert row.state == "RETRY_WAIT"
    actor = auto._authorizer(execution.authorizer_user_id)
    auto.set_policy(actor, enabled=False, current_version=execution.policy_version)
    assert worker().run_once()
    db.expire_all()
    assert db.get(AgentWorkflowRun, row.run_id).state == "FINISHED"
    assert worker().run_once() is False and len(cloud.starts) == 1
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_unknown_remote_creation_keeps_capacity_until_reconciled(prepared_dispatch):
    from app.modules.agent.change_dispatcher import ChangeDispatcher
    from tests.unit.agent.test_auto_change import request
    from tests.unit.agent.test_change_runtime import connection

    db, auto, _, old, cloud, _, factory = prepared_dispatch
    extra = auto.register(request(db, old).id)
    db.commit()
    cloud.failure = AdpCallError("UPSTREAM_UNCERTAIN", ambiguous=True)
    worker = ChangeDispatcher(
        factory,
        [connection()],
        environment="dev",
        app_key_id="change-app",
        client=cloud,
        max_active=1,
    )
    assert worker.run_once()
    assert worker.run_once() is False
    assert len(cloud.starts) == 1
    assert db.get(type(extra), extra.id).status == "QUEUED"


def test_expired_poll_attempt_cannot_overwrite_newer_observation(prepared_dispatch):
    from tests.unit.agent.test_change_runtime import connection

    db, _, _, _, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    row = force_poll(db)
    service = DispatchService(
        db, [connection()], environment="dev", app_key_id="change-app", config=cloud.config
    )
    old = service.reserve_poll()
    row.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    new = service.reserve_poll()
    assert new.attempt_token != old.attempt_token
    assert service.record_poll(old, AdpSnapshot("wfr-durable-one", "SUCCEEDED", "old")) is False
    assert service.record_poll(new, AdpSnapshot("wfr-durable-one", "RUNNING", "new")) is True
    assert row.remote_status == "RUNNING"


def test_late_create_ack_keeps_remote_id_without_reenabling_run(prepared_dispatch):
    from tests.unit.agent.test_change_runtime import connection

    db, _, _, _, cloud, _, _ = prepared_dispatch
    service = DispatchService(
        db, [connection()], environment="dev", app_key_id="change-app", config=cloud.config
    )
    claim = service.reserve_start()
    row = db.get(AgentWorkflowRun, claim.run_id)
    row.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert service.recover_start()
    assert service.record_start(claim, AdpCreated("wfr-late", "req-late"))
    assert row.remote_run_id == "wfr-late" and row.state == "WAITING"
    assert db.get(AgentRun, claim.run_id).revoked_at is not None


def test_only_definite_create_rejections_retry_at_most_three_times(prepared_dispatch):
    db, _, _, _, cloud, worker, _ = prepared_dispatch
    cloud.failure = AdpCallError("UPSTREAM_REJECTED", retryable=True)
    for index in range(3):
        assert worker().run_once()
        db.expire_all()
        row = db.scalar(select(AgentWorkflowRun))
        assert row.create_attempts == index + 1
        if index < 2:
            assert row.state == "RETRY_WAIT"
            force_poll(db)
    assert row.state == "FINISHED" and len(cloud.starts) == 3
    assert len({value[0] for value in cloud.starts}) == 3
    assert db.query(AgentWorkflowRun).count() == 1


def test_manual_observation_releases_known_terminal_cloud_run_without_restoring_writes(
    prepared_dispatch,
):
    db, _, _, old, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    row = force_poll(db)
    row.deadline_at = utcnow() - timedelta(seconds=1)
    db.commit()
    worker().run_once()
    cloud.status = "CANCELED"
    assert worker().observe_once(row.run_id)
    db.expire_all()
    row = db.get(AgentWorkflowRun, row.run_id)
    assert row.state == "FINISHED" and row.remote_status == "CANCELED"
    assert db.get(AgentRun, row.run_id).revoked_at is not None
    assert db.get(InspectionAssignment, old.id).revoked_at is None
    assert len(cloud.starts) == 1


def test_cli_rejects_disabled_worker_before_constructing_cloud_client(monkeypatch):
    from types import SimpleNamespace

    from app.modules.agent import change_dispatcher

    monkeypatch.setattr("sys.argv", ["change-dispatcher", "--once"])
    monkeypatch.setattr(
        change_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(
            agent_worker_enabled=False,
            agent_auto_change_enabled=False,
            agent_tools_enabled=False,
            agent_adp_enabled=False,
        ),
    )
    with pytest.raises(SystemExit, match="disabled"):
        change_dispatcher.main()


def test_dispatch_migration_preserves_cloud_tracking_history(prepared_dispatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    db, _, _, _, _, worker, _ = prepared_dispatch
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a005_cloud_workflow.py"
    spec = importlib.util.spec_from_file_location("cloud_workflow_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE agent_workflow_run"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
    worker().run_once()
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        with pytest.raises(RuntimeError, match="workflow"):
            migration.downgrade()
        assert "agent_workflow_run" in inspect(connection).get_table_names()


def test_tracking_does_not_store_credentials_and_token_expires_by_dispatch_deadline(
    prepared_dispatch,
):
    db, _, _, _, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    row = db.scalar(select(AgentWorkflowRun))
    run = db.get(AgentRun, row.run_id)
    assert run.credential_expires_at <= row.deadline_at
    values = {
        column.name: getattr(row, column.name) for column in AgentWorkflowRun.__table__.columns
    }
    assert cloud.starts[0][0] not in str(values)
    assert "synthetic-secret-key" not in str(values)


def test_corrupt_local_success_flag_is_not_a_commit_receipt(prepared_dispatch):
    db, _, execution, old, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    force_poll(db)
    execution.status, execution.result_json = "SUCCEEDED", {"status": "SUCCEEDED"}
    db.commit()
    cloud.status = "SUCCEEDED"
    worker().run_once()
    db.expire_all()
    row = db.scalar(select(AgentWorkflowRun))
    assert row.outcome == "UNKNOWN" and row.error_code == "LOCAL_RECEIPT_INVALID"
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_dispatcher_does_not_claim_a_source_from_another_environment(prepared_dispatch):
    db, _, execution, _, cloud, worker, _ = prepared_dispatch
    execution.environment = "prod"
    db.commit()
    assert worker().run_once() is False
    assert cloud.starts == []


@pytest.mark.parametrize("field,value", [("environment", "prod"), ("app_key_id", "other-app")])
def test_dispatcher_does_not_poll_or_revoke_another_runtime(prepared_dispatch, field, value):
    db, _, _, _, cloud, worker, _ = prepared_dispatch
    worker().run_once()
    row = force_poll(db)
    run = db.get(AgentRun, row.run_id)
    setattr(run, field, value)
    db.commit()
    assert worker().run_once() is False
    db.expire_all()
    assert cloud.polls == []
    assert db.get(AgentRun, row.run_id).revoked_at is None


def test_missing_tool_application_configuration_does_not_consume_business_requests(
    prepared_dispatch,
):
    db, _, execution, _, cloud, worker, _ = prepared_dispatch
    instance = worker()
    instance.connections = []
    assert instance.run_once() is False
    db.expire_all()
    assert db.get(type(execution), execution.id).status == "QUEUED"
    assert cloud.starts == [] and db.query(AgentWorkflowRun).count() == 0


def test_source_environment_migration_never_guesses_legacy_provenance(prepared_dispatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    db, _, execution, _, _, worker, _ = prepared_dispatch
    path = (
        Path(__file__).parents[3] / "migrations/versions/f26a1024a006_change_source_environment.py"
    )
    spec = importlib.util.spec_from_file_location("change_source_environment_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("ALTER TABLE auto_change_execution DROP COLUMN environment"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.scalar(text("SELECT environment FROM auto_change_execution")) is None
            migration.downgrade()
            migration.upgrade()
    db.expire_all()
    assert worker().run_once() is False
    execution.environment = "dev"
    db.commit()
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="provenance"),
    ):
        migration.downgrade()
