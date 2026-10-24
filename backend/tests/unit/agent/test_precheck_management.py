import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.agent.adp_client import AdpCreated, AdpSnapshot
from app.modules.agent.models import AgentRun, AgentWorkflowRun
from app.modules.agent.run_context import RunService
from app.modules.objection.precheck_management import PrecheckManagementService
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from sqlalchemy import select
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result
from tests.unit.agent.test_objection_runtime import connection


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_objection_adp_client import precheck_config

    settings = get_settings()
    for field, value in {
        "agent_tools_enabled": True,
        "agent_worker_enabled": True,
        "agent_adp_enabled": True,
        "agent_adp_objection_config": precheck_config(),
        "agent_objection_app_key_id": "objection-app",
        "agent_tool_connections": [connection()],
    }.items():
        monkeypatch.setattr(settings, field, value)
    yield from case_fixture.__wrapped__(monkeypatch)


def failed(case):
    db, _, cid, _, obj, _ = case
    svc, job = queue(case)
    job.status, job.error_code = "FAILED", "SYNTHETIC_AI_FAILURE"
    db.commit()
    return PrecheckManagementService(db, cid), svc, job, obj


def test_latest_status_is_case_scoped_and_does_not_return_execution_credentials(case):
    db, teacher, cid, other, obj, foreign = case
    service, _, job, _ = failed(case)
    view = service.latest(teacher, obj.id)
    assert view["job_id"] == str(job.id) and view["can_retry"]
    assert "attempt_token" not in view and "credential_digest" not in view
    with pytest.raises(NotFoundError):
        service.latest(teacher, foreign.id)
    with pytest.raises(NotFoundError):
        PrecheckManagementService(db, other).latest(teacher, obj.id)


def test_retry_appends_history_and_repeated_request_returns_the_same_attempt(case):
    db, teacher, _, _, _, _ = case
    service, _, old, obj = failed(case)
    first = service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)
    second = service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)
    assert first["job_id"] == second["job_id"] and first["job_id"] != str(old.id)
    new = db.get(ObjectionPrecheckJob, int(first["job_id"]))
    assert old.status == "FAILED" and new.status == "QUEUED"
    assert new.retry_of_job_id == old.id and new.attempt_no == 2
    assert new.initiated_by_user_id == teacher.id
    assert len(db.scalars(select(ObjectionPrecheckJob)).all()) == 2


def test_current_running_or_succeeded_task_is_not_duplicated_by_retry(case):
    db, teacher, cid, _, obj, _ = case
    svc, job = queue(case)
    service = PrecheckManagementService(db, cid)
    same = service.retry(teacher, obj.id, expected_job_id=job.id, request_id=None)
    assert same["job_id"] == str(job.id)
    svc.finish(job.id, svc.begin(job.id), result())
    assert service.retry(teacher, obj.id, expected_job_id=job.id, request_id=None)["job_id"] == str(
        job.id
    )
    assert db.query(ObjectionPrecheckJob).count() == 1


def test_untracked_running_identity_blocks_new_model_execution(case):
    db, teacher, cid, _, obj, _ = case
    svc, job = queue(case)
    svc.begin(job.id)
    run, _ = RunService(db, [connection()], environment="dev").issue_objection(
        "objection-app", job.id
    )
    job.status, job.attempt_token = "FAILED", None
    db.commit()
    service = PrecheckManagementService(db, cid)
    assert service.latest(teacher, obj.id)["retry_block_reason"] == "UNTRACKED_EXECUTION"
    with pytest.raises(ConflictError):
        service.retry(teacher, obj.id, expected_job_id=job.id, request_id=None)
    assert db.get(AgentRun, run.id) is not None and db.query(ObjectionPrecheckJob).count() == 1


@pytest.mark.parametrize("cloud_state", ["UNCERTAIN", "TIMED_OUT", "OBSERVATION_FAILED", "WAITING"])
def test_retry_needs_confirmed_cloud_end_before_creating_another_attempt(case, cloud_state):
    from app.modules.agent.objection_dispatcher import ObjectionDispatchService
    from tests.unit.agent.test_objection_dispatcher import ObjectionCloud

    db, teacher, cid, _, obj, _ = case
    _, job = queue(case)
    dispatch = ObjectionDispatchService(
        db,
        [connection()],
        environment="dev",
        app_key_id="objection-app",
        config=ObjectionCloud().config,
    )
    claim = dispatch.reserve_start()
    dispatch.record_start(claim, AdpCreated("wfr-test", "req-test"))
    tracked = db.get(AgentWorkflowRun, claim.run_id)
    tracked.state, job.status = cloud_state, "FAILED"
    db.commit()
    with pytest.raises(ConflictError):
        PrecheckManagementService(db, cid).retry(
            teacher, obj.id, expected_job_id=job.id, request_id=None
        )
    assert db.query(ObjectionPrecheckJob).count() == 1


def test_confirmed_cloud_failure_allows_new_attempt_and_old_identity_stays_revoked(case):
    from app.modules.agent.objection_dispatcher import ObjectionDispatchService
    from tests.unit.agent.test_change_dispatcher import force_poll
    from tests.unit.agent.test_objection_dispatcher import ObjectionCloud

    db, teacher, cid, _, obj, _ = case
    _, job = queue(case)
    dispatch = ObjectionDispatchService(
        db,
        [connection()],
        environment="dev",
        app_key_id="objection-app",
        config=ObjectionCloud().config,
    )
    claim = dispatch.reserve_start()
    dispatch.record_start(claim, AdpCreated("wfr-test", "req-test"))
    force_poll(db)
    poll = dispatch.reserve_poll()
    dispatch.record_poll(poll, AdpSnapshot("wfr-test", "FAILED", "req-fail"))
    view = PrecheckManagementService(db, cid).retry(
        teacher, obj.id, expected_job_id=job.id, request_id=None
    )
    assert view["job_id"] != str(job.id)
    assert db.get(AgentRun, claim.run_id).revoked_at is not None


def test_missing_policy_or_revoked_actual_teacher_role_cannot_retry(case):
    from app.modules.identity.models import Role, UserRole
    from sqlalchemy import delete

    db, teacher, cid, _, obj, _ = case
    service, svc, old, _ = failed(case)
    svc.set_policy(teacher, enabled=False, current_version=1)
    with pytest.raises(ConflictError):
        service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)
    role = db.scalar(select(Role).where(Role.code == "TEACHER_ADMIN"))
    db.execute(delete(UserRole).where(UserRole.user_id == teacher.id, UserRole.role_id == role.id))
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)


def test_finalized_objection_and_stale_expected_job_cannot_start_new_work(case):
    db, teacher, _, _, _, _ = case
    service, _, old, obj = failed(case)
    with pytest.raises(ConflictError):
        service.retry(teacher, obj.id, expected_job_id=old.id + 99, request_id=None)
    obj.final_status = "REJECTED"
    db.commit()
    with pytest.raises(ConflictError):
        service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)


def test_policy_read_rechecks_actual_authority_and_shows_configuration_readiness(case, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_adp_objection_config", None)
    db, teacher, cid, _, _, _ = case
    service = PrecheckManagementService(db, cid)
    policy = service.policy(teacher)
    assert policy["enabled"] is False and policy["version"] == 0
    assert policy["configuration_ready"] is False
    with pytest.raises(ConflictError):
        service.update_policy(teacher, enabled=True, current_version=0)


def test_retry_failure_rolls_back_new_attempt_and_preserves_old_history(case, monkeypatch):
    db, teacher, _, _, _, _ = case
    service, _, old, obj = failed(case)

    def fail_commit():
        raise RuntimeError("synthetic retry commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic retry"):
            service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)
    db.refresh(old)
    assert old.status == "FAILED" and db.query(ObjectionPrecheckJob).count() == 1


def test_archived_semester_remains_readable_but_cannot_start_new_precheck(case):
    from app.modules.academic.models import Semester
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.inspection.models import InspectionTask

    db, teacher, _, _, _, _ = case
    service, _, old, obj = failed(case)
    task = db.get(InspectionTask, db.get(AttendanceRecord, obj.attendance_record_id).task_id)
    db.get(Semester, task.semester_id).status = "ARCHIVED"
    db.commit()
    view = service.latest(teacher, obj.id)
    assert not view["can_retry"] and view["retry_block_reason"] == "SEMESTER_ARCHIVED"
    with pytest.raises(ConflictError):
        service.retry(teacher, obj.id, expected_job_id=old.id, request_id=None)


def test_retry_migration_preserves_initial_jobs_and_refuses_to_erase_attempt_history(case):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    db, teacher, _, _, _, _ = case
    service, _, old, obj = failed(case)
    old_id = old.id
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a009_precheck_retries.py"
    spec = importlib.util.spec_from_file_location("precheck_retry_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.commit()
    with db.bind.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
        assert conn.scalar(text("SELECT id FROM objection_precheck_job")) == old_id
        migration.upgrade()
        assert conn.scalar(text("SELECT attempt_no FROM objection_precheck_job")) == 1
    db.expire_all()
    view = service.retry(teacher, obj.id, expected_job_id=old_id, request_id=None)
    assert view["job_id"] != str(old_id)
    with (
        db.bind.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
        pytest.raises(RuntimeError, match="retry history"),
    ):
        migration.downgrade()
