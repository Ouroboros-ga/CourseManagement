import importlib.util
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import Base, utcnow
from sqlalchemy import inspect, text


def migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1025a010_conversations.py"
    assert path.exists(), "Conversation migration is missing"
    spec = importlib.util.spec_from_file_location("conversation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_report_export_prepare import fixture as report_fixture

    original = report_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def test_sqlite_upgrade_matches_models_and_refuses_to_erase_conversations(case):
    module = migration()
    db = case[0][1]
    source = case[2].resolve("m" * 40, case[3])
    from app.modules.agent.models import AgentRun

    run = db.get(AgentRun, int(source.run_id))
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE agent_turn"))
        connection.execute(text("DROP TABLE agent_conversation"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            for name in ("agent_conversation", "agent_turn"):
                actual = {column["name"] for column in inspect(connection).get_columns(name)}
                assert actual == set(Base.metadata.tables[name].columns.keys())
            module.downgrade()
            module.upgrade()
            connection.execute(
                text(
                    "INSERT INTO agent_conversation (actor_user_id, source_session_id, college_id, "
                    "semester_id, environment, app_key_id, remote_conversation_id, "
                    "scope_hash, state, expires_at, created_at, updated_at) "
                    "VALUES (:actor, :session, :college, :semester, "
                    "'dev', 'management', :remote, :hash, 'OPEN', :expiry, :now, :now)"
                ),
                {
                    "actor": case[1].id,
                    "session": run.source_session_id,
                    "college": run.college_id,
                    "semester": run.semester_id,
                    "remote": "c" * 32,
                    "hash": "h" * 64,
                    "expiry": utcnow() + timedelta(hours=24),
                    "now": utcnow(),
                },
            )
            with pytest.raises(RuntimeError, match="agent_conversation"):
                module.downgrade()
            assert {"agent_conversation", "agent_turn"} <= set(
                inspect(connection).get_table_names()
            )


def test_mysql_offline_upgrade_has_bounded_indexes_and_restrictive_foreign_keys():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE agent_conversation" in ddl and "CREATE TABLE agent_turn" in ddl
    assert "DATETIME(3)" in ddl and "ENGINE=InnoDB" in ddl
    assert "uq_agent_turn_request" in ddl and "ON DELETE RESTRICT" in ddl
    assert "reply MEDIUMTEXT" in ddl
