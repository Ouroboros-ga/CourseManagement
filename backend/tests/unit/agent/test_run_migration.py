import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import utcnow
from sqlalchemy import inspect, text
from tests.unit.agent.test_run_context import session_for
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def load_migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a001_agent_run.py"
    spec = importlib.util.spec_from_file_location("agent_run_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_upgrades_empty_database_and_refuses_to_erase_runs(campus):
    migration = load_migration()
    db = campus[1]
    auth = session_for(db, campus[3])
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE agent_run"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "agent_run" in inspect(connection).get_table_names()
            migration.downgrade()
            assert "agent_run" not in inspect(connection).get_table_names()
            migration.upgrade()
            connection.execute(
                text(
                    "INSERT INTO agent_run (app_key_id, entry_kind, environment, actor_user_id, "
                    "source_session_id, credential_digest, credential_expires_at, status, "
                    "created_at, updated_at) VALUES ('self', 'SELF_SERVICE', 'dev', :actor, "
                    ":session, :digest, :expiry, 'ACTIVE', :now, :now)"
                ),
                {
                    "actor": campus[3].id,
                    "session": auth.id,
                    "digest": "a" * 64,
                    "expiry": utcnow() + timedelta(minutes=10),
                    "now": utcnow(),
                },
            )
            with pytest.raises(RuntimeError, match="agent_run"):
                migration.downgrade()
