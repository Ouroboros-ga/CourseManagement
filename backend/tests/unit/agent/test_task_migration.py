import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import utcnow
from sqlalchemy import inspect, text
from tests.unit.agent.test_jobs import arrange
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_queue_migration_and_non_destructive_downgrade(campus):
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a002_agent_tasks.py"
    spec = importlib.util.spec_from_file_location("agent_tasks_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db, user, auth, run = arrange(campus)
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE agent_job"))
        connection.execute(text("DROP TABLE agent_task"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {"agent_task", "agent_job"} <= set(inspect(connection).get_table_names())
            migration.downgrade()
            migration.upgrade()
            connection.execute(
                text(
                    "INSERT INTO agent_task (run_id, actor_user_id, source_session_id, "
                    "request_key, "
                    "input_hash, scope_hash, status, created_at, updated_at) "
                    "VALUES (:run, :actor, :session, 'one', :hash, :hash, 'QUEUED', :now, :now)"
                ),
                {
                    "run": run.id,
                    "actor": user.id,
                    "session": auth.id,
                    "hash": "a" * 64,
                    "now": utcnow(),
                },
            )
            with pytest.raises(RuntimeError, match="agent_task"):
                migration.downgrade()
