from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.adp_schemas import ObjectionAdpConfiguration
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.models import AgentRun, AgentWorkflowRun
from app.modules.agent.objection_dispatcher import ObjectionDispatcher
from app.modules.agent.run_context import RunService
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from tests.unit.agent.test_change_dispatcher import Cloud, force_poll
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result
from tests.unit.agent.test_objection_runtime import connection


class ObjectionCloud(Cloud):
    def __init__(self):
        super().__init__()
        self.config = ObjectionAdpConfiguration(
            **{**self.config.model_dump(), "app_id": "987654321"},
            proof_delivery_verified=True,
        )
        self.on_start = None

    def start_objection(self, token, *, caller_ref):
        if self.on_start:
            self.on_start()
        return super().start_change(token, caller_ref=caller_ref)

    def start_change(self, *args, **kwargs):
        raise AssertionError("precheck must not invoke the change workflow")


@pytest.fixture(name="prepared")
def fixture(monkeypatch):
    source = case_fixture.__wrapped__(monkeypatch)
    case = next(source)
    svc, job = queue(case)
    db = case[0]
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    cloud = ObjectionCloud()
    monkeypatch.setattr(get_settings(), "agent_adp_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_tools_enabled", True)

    def worker(**limits):
        return ObjectionDispatcher(
            factory,
            [connection()],
            environment="dev",
            app_key_id="objection-app",
            client=cloud,
            **limits,
        )

    try:
        yield db, svc, job, cloud, worker, factory, case
    finally:
        source.close()


def test_claim_and_tracking_commit_before_network_then_restart_observes_same_instance(prepared):
    db, _, job, cloud, worker, factory, case = prepared

    def before_network():
        with factory() as session:
            assert session.get(ObjectionPrecheckJob, job.id).status == "RUNNING"
            assert session.scalar(select(AgentWorkflowRun)).state == "STARTING"

    cloud.on_start = before_network
    assert worker().run_once()
    tracked = force_poll(db)
    cloud.status = "SUCCEEDED"
    assert worker().run_once()
    db.expire_all()
    assert db.get(ObjectionPrecheckJob, job.id).status == "FAILED"
    assert db.get(AgentWorkflowRun, tracked.run_id).outcome == "MANUAL_REQUIRED"
    assert case[4].final_status == "PENDING"
    assert len(cloud.starts) == 1 and cloud.polls == [tracked.remote_run_id]


def test_real_advice_receipt_wins_over_cloud_failure_without_formal_review(prepared):
    db, _, job, cloud, worker, factory, case = prepared
    assert worker().run_once()

    def save_advice():
        with factory() as session:
            context = RunService(session, [connection()], environment="dev").resolve(
                "o" * 40, cloud.starts[0][0]
            )
            invoke_tool(
                session, context, "objection_precheck_save", {"result": result().model_dump()}
            )

    cloud.on_poll, cloud.status = save_advice, "FAILED"
    tracked = force_poll(db)
    assert worker().run_once()
    db.expire_all()
    assert db.get(ObjectionPrecheckJob, job.id).status == "SUCCEEDED"
    assert db.get(AgentWorkflowRun, tracked.run_id).outcome == "SUCCEEDED"
    assert db.get(AgentWorkflowRun, tracked.run_id).remote_status == "FAILED"
    assert case[4].final_status == "PENDING"


def test_unknown_create_fails_job_revokes_token_and_retains_capacity_without_recreate(prepared):
    db, svc, job, cloud, worker, _, case = prepared
    cloud.failure = AdpCallError("UPSTREAM_UNCERTAIN", ambiguous=True)
    assert worker(max_active=1).run_once()
    tracked = db.scalar(select(AgentWorkflowRun))
    db.expire_all()
    assert tracked.state == "UNCERTAIN"
    assert db.get(ObjectionPrecheckJob, job.id).status == "FAILED"
    assert db.get(AgentRun, tracked.run_id).revoked_at is not None
    case[4].reason = "补充说明"
    db.commit()
    another = svc.enqueue(case[4].id, case[1].id)
    db.commit()
    assert another.id != job.id
    assert worker(max_active=1).run_once() is False
    assert len(cloud.starts) == 1


def test_expired_start_is_not_created_again_after_restart(prepared):
    db, _, job, cloud, worker, _, _ = prepared
    service = worker()._service(db)
    claim = service.reserve_start()
    tracked = db.get(AgentWorkflowRun, claim.run_id)
    tracked.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker().run_once()
    db.expire_all()
    assert tracked.state == "UNCERTAIN" and job.status == "FAILED"
    assert cloud.starts == []


def test_explicit_create_rejection_retries_with_rotated_token_on_same_job(prepared):
    db, _, job, cloud, worker, _, _ = prepared
    cloud.failure = AdpCallError("THROTTLED", retryable=True)
    assert worker().run_once()
    force_poll(db)
    cloud.failure = None
    assert worker().run_once()
    assert len(cloud.starts) == 2 and cloud.starts[0][0] != cloud.starts[1][0]
    assert db.query(AgentRun).count() == 1
    with pytest.raises(AppError):
        RunService(db, [connection()], environment="dev").resolve("o" * 40, cloud.starts[0][0])
    db.refresh(job)
    assert db.get(ObjectionPrecheckJob, job.id).status == "RUNNING"


def test_disabled_policy_is_recorded_without_consuming_model_capacity(prepared):
    db, svc, job, cloud, worker, _, case = prepared
    svc.set_policy(case[1], enabled=False, current_version=1)
    assert worker().run_once()
    db.expire_all()
    assert job.status == "FAILED" and cloud.starts == []
    assert db.query(AgentWorkflowRun).count() == 0


def test_unverified_proof_delivery_and_wrong_application_leave_job_queued(prepared, monkeypatch):
    db, _, job, cloud, worker, _, _ = prepared
    cloud.config = cloud.config.model_copy(update={"proof_delivery_verified": False})
    assert worker().run_once() is False
    cloud.config = cloud.config.model_copy(update={"proof_delivery_verified": True})
    monkeypatch.setattr(get_settings(), "agent_adp_config", cloud.config)
    assert worker().run_once() is False
    db.refresh(job)
    assert job.status == "QUEUED" and cloud.starts == []


def test_failed_tracking_commit_rolls_back_claim_and_run_identity(prepared, monkeypatch):
    db, _, job, cloud, worker, _, _ = prepared
    service = worker()._service(db)

    def fail_commit():
        raise RuntimeError("synthetic tracking failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic tracking"):
            service.reserve_start()
    db.refresh(job)
    assert job.status == "QUEUED" and job.attempt_token is None
    assert db.query(AgentRun).count() == db.query(AgentWorkflowRun).count() == 0


def test_timeout_then_observation_only_reconciles_the_saved_instance(prepared):
    db, _, job, cloud, worker, _, _ = prepared
    assert worker().run_once()
    tracked = force_poll(db)
    tracked.deadline_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker().run_once()
    db.expire_all()
    assert tracked.state == "TIMED_OUT" and job.status == "FAILED"
    cloud.status = "FAILED"
    assert worker().observe_once(tracked.run_id)
    db.refresh(tracked)
    assert tracked.state == "FINISHED" and len(cloud.starts) == 1


def test_foreign_environment_queue_is_not_claimed(prepared):
    db, _, job, cloud, worker, _, _ = prepared
    job.environment = "production-isolated"
    db.commit()
    assert worker().run_once() is False
    assert cloud.starts == [] and job.status == "QUEUED"


def test_changed_source_is_stale_before_model_creation(prepared):
    db, _, job, cloud, worker, _, case = prepared
    case[4].reason = "补充新理由"
    db.commit()
    assert worker().run_once()
    db.refresh(job)
    assert job.status == "STALE" and job.error_code == "SOURCE_CHANGED"
    assert cloud.starts == []


def test_cloud_success_with_fabricated_local_status_is_not_a_verified_advice_receipt(prepared):
    db, _, job, cloud, worker, _, _ = prepared
    worker().run_once()
    tracked = force_poll(db)
    job.status, job.result_json = "SUCCEEDED", result().model_dump()
    db.commit()
    cloud.status = "SUCCEEDED"
    assert worker().run_once()
    db.refresh(tracked)
    assert tracked.outcome == "UNKNOWN" and tracked.error_code == "LOCAL_RECEIPT_INVALID"
