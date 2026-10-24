from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.exceptions import AppError, ConflictError
from app.modules.agent.models import AgentJob, AgentTask
from app.modules.agent.run_context import RunService
from app.modules.agent.task_service import TaskService
from app.modules.agent.worker import Worker
from sqlalchemy.orm import Session, sessionmaker
from tests.unit.agent.test_run_context import connection, session_for
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def arrange(campus):
    db, user = campus[1], campus[3]
    auth = session_for(db, user)
    run, _ = RunService(db, [connection()], environment="dev").issue("self-app", user.id, auth.id)
    return db, user, auth, run


def test_enqueue_is_durable_and_idempotent(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    assert task.status == "QUEUED"
    again = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    assert again.id == task.id
    with pytest.raises(ConflictError):
        service.submit(
            run.id, user.id, auth.id, "self_timetable_get", {"semester_id": "1"}, "request-1"
        )
    with Session(db.bind) as restarted:
        assert restarted.get(AgentTask, task.id).status == "QUEUED"
        assert restarted.query(AgentJob).count() == 1


def test_worker_restores_session_and_publishes_real_result(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    worker = Worker(sessionmaker(bind=db.bind), [connection()], environment="dev")
    assert worker.run_once()
    db.expire_all()
    result = service.read(task.id, user.id)
    assert result["status"] == "SUCCEEDED"
    assert result["result"]["data"] == {"contract_version": "v1"}
    assert not worker.run_once()


def test_expired_attempt_cannot_overwrite_reclaimed_job(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    first = service.claim("first")
    assert first
    job = db.get(AgentJob, first.job_id)
    job.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    second = service.claim("second")
    assert second and first.attempt_token != second.attempt_token
    assert not service.finish(first, {"wrong": True})
    assert service.finish(second, {"correct": True})
    assert service.read(task.id, user.id)["result"] == {"correct": True}


def test_logout_during_queue_prevents_execution(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    auth.revoked_at = utcnow()
    db.commit()
    worker = Worker(sessionmaker(bind=db.bind), [connection()], environment="dev")
    assert worker.run_once()
    db.expire_all()
    assert db.get(AgentTask, task.id).status == "FAILED"
    assert db.get(AgentJob, 1).result_json is None


def test_cancellation_fences_running_result_and_other_users(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    claim = service.claim("worker")
    with pytest.raises(AppError):
        service.read(task.id, campus[2].id)
    service.cancel(task.id, user.id)
    assert not service.finish(claim, {"late": True})
    assert service.read(task.id, user.id)["status"] == "CANCELED"


def test_enqueue_rolls_back_with_parent_business_transaction(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.rollback()
    assert db.query(AgentTask).count() == 0
    assert db.query(AgentJob).count() == 0


def test_queue_admission_is_bounded_but_replay_is_still_available(campus, monkeypatch):
    from app.core.config import get_settings

    db, user, auth, run = arrange(campus)
    monkeypatch.setattr(get_settings(), "agent_run_max_pending_tasks", 1)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    with pytest.raises(AppError) as error:
        service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-2")
    assert error.value.http_status == 429
    assert service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1").id == task.id


def test_last_abandoned_attempt_becomes_terminal(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    for _ in range(3):
        claim = service.claim("worker")
        assert claim
        db.get(AgentJob, claim.job_id).lease_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert service.claim("worker") is None
    result = service.read(task.id, user.id)
    assert result["status"] == "FAILED"
    assert result["error_code"] == "ATTEMPTS_EXHAUSTED"


def test_temporary_failure_has_bounded_backoff(campus, monkeypatch):
    from app.modules.agent import worker as worker_module
    from sqlalchemy.exc import OperationalError

    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()

    def fail(*_):
        raise OperationalError("operation", {}, Exception("temporary"))

    monkeypatch.setattr(worker_module, "invoke_tool", fail)
    worker = Worker(sessionmaker(bind=db.bind), [connection()], environment="dev")
    for attempt in range(1, 4):
        assert worker.run_once()
        db.expire_all()
        job = db.query(AgentJob).one()
        assert job.attempt_count == attempt
        if attempt < 3:
            assert job.status == "QUEUED" and job.available_at > utcnow()
            job.available_at = utcnow() - timedelta(seconds=1)
            db.commit()
    assert service.read(task.id, user.id)["status"] == "FAILED"
    assert not worker.run_once()


def test_token_ttl_does_not_cancel_a_valid_queued_task(campus):
    db, user, auth, run = arrange(campus)
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    run.credential_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    worker = Worker(sessionmaker(bind=db.bind), [connection()], environment="dev")
    assert worker.run_once()
    assert service.read(task.id, user.id)["status"] == "SUCCEEDED"


def test_status_tool_is_bound_to_current_run(campus, monkeypatch):
    from app.core.config import get_settings
    from app.modules.agent.gateway import invoke_tool

    monkeypatch.setattr(get_settings(), "agent_tool_connections", [connection()])
    db, user, auth, run = arrange(campus)
    runs = RunService(db, [connection()], environment="dev")
    service = TaskService(db, [connection()], environment="dev")
    task = service.submit(run.id, user.id, auth.id, "system_probe", {}, "request-1")
    db.commit()
    result = invoke_tool(db, runs.restore(run.id), "task_status_get", {"task_id": str(task.id)})
    assert result.data["status"] == "QUEUED"
    other, _ = runs.issue("self-app", user.id, auth.id)
    with pytest.raises(AppError):
        invoke_tool(db, runs.restore(other.id), "task_status_get", {"task_id": str(task.id)})


def test_stored_management_result_is_hidden_after_business_scope_is_disabled(campus, monkeypatch):
    from app.core.config import get_settings
    from app.modules.agent.run_context import AppConnection
    from app.modules.inspection.models import InspectionTask
    from tests.unit.test_scoped_file_access import setup

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    auth = session_for(db, actor)
    app = AppConnection(
        app_key_id="management", entry_kind="MANAGEMENT", environment="dev", key_digest="a" * 64
    )
    run, _ = RunService(db, [app], environment="dev").issue(
        "management", actor.id, auth.id, college_id=int(campus[4]["id"])
    )
    source = db.query(InspectionTask).filter_by(college_id=int(campus[4]["id"])).first()
    service = TaskService(db, [app], environment="dev")
    task = service.submit(
        run.id,
        actor.id,
        auth.id,
        "report_attendance_summary",
        {"semester_id": str(source.semester_id), "week_no": source.week_no},
        "one",
    )
    db.commit()
    assert Worker(sessionmaker(bind=db.bind), [app], environment="dev").run_once()
    assert service.read(task.id, actor.id)["status"] == "SUCCEEDED"
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", False)
    with pytest.raises(AppError):
        service.read(task.id, actor.id)
