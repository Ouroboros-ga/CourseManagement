"""Destructive fixtures are inherited from the protected *_test database suite."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from threading import Barrier

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.modules.agent.models import AgentJob, AgentTask
from app.modules.agent.run_context import AppConnection, RunService
from app.modules.agent.task_service import TaskService
from app.modules.identity.models import AuthSession, Role, UserAccount, UserRole
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration


def prepare(db):
    environment = get_settings().app_env
    connection = AppConnection(
        app_key_id="test-self",
        entry_kind="SELF_SERVICE",
        key_digest=sha256(b"test-app-key-not-used-over-network").hexdigest(),
        environment=environment,
    )
    user, role = (
        UserAccount(display_name="Synthetic student", status="ACTIVE"),
        Role(code="STUDENT", name="Student"),
    )
    db.add_all([user, role])
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    auth = AuthSession(
        user_id=user.id,
        client_type="WECHAT",
        refresh_token_hash="0" * 64,
        refresh_family_id="synthetic-agent-family",
        expires_at=utcnow() + timedelta(days=1),
    )
    db.add(auth)
    db.commit()
    run, _ = RunService(db, [connection], environment=environment).issue(
        connection.app_key_id, user.id, auth.id
    )
    return connection, environment, run.id, user.id, auth.id


def test_mysql_concurrent_submissions_share_one_durable_job(engine, session):
    connection, environment, run_id, user_id, sid = prepare(session)
    factory = sessionmaker(bind=engine)
    barrier = Barrier(4)

    def submit(_):
        with factory() as db:
            barrier.wait(timeout=10)
            task = TaskService(db, [connection], environment=environment).submit(
                run_id, user_id, sid, "system_probe", {}, "same-request"
            )
            task_id = task.id
            db.commit()
            return task_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        task_ids = list(pool.map(submit, range(4)))
    assert len(set(task_ids)) == 1
    assert session.scalar(select(func.count()).select_from(AgentTask)) == 1
    assert session.scalar(select(func.count()).select_from(AgentJob)) == 1


def test_mysql_claim_is_exclusive_and_expired_result_is_fenced(engine, session):
    connection, environment, run_id, user_id, sid = prepare(session)
    service = TaskService(session, [connection], environment=environment)
    task = service.submit(run_id, user_id, sid, "system_probe", {}, "one")
    session.commit()
    factory = sessionmaker(bind=engine)
    barrier = Barrier(2)

    def claim(index):
        with factory() as db:
            barrier.wait(timeout=10)
            return TaskService(db, [connection], environment=environment).claim(f"worker-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = [value for value in pool.map(claim, range(2)) if value is not None]
    assert len(claims) == 1
    first = claims[0]
    session.get(AgentJob, first.job_id).lease_until = utcnow() - timedelta(seconds=1)
    session.commit()
    second = service.claim("replacement")
    assert second and first.attempt_token != second.attempt_token
    assert not service.finish(first, {"stale": True})
    assert service.finish(second, {"fresh": True})
    assert service.read(task.id, user_id)["result"] == {"fresh": True}


def test_mysql_enqueue_is_part_of_parent_transaction(session):
    connection, environment, run_id, user_id, sid = prepare(session)
    TaskService(session, [connection], environment=environment).submit(
        run_id, user_id, sid, "system_probe", {}, "rollback"
    )
    session.rollback()
    assert session.scalar(select(func.count()).select_from(AgentTask)) == 0
    assert session.scalar(select(func.count()).select_from(AgentJob)) == 0
