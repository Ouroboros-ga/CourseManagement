import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1025a011_chat_queue.py"
    assert path.exists(), "Chat queue migration is missing"
    spec = importlib.util.spec_from_file_location("chat_queue_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_chat_queue import fixture as queue_fixture

    original = queue_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def test_sqlite_evolution_and_queued_downgrade_guard_preserve_history(case):
    from tests.unit.agent.test_chat_queue import arrange, enqueue
    from tests.unit.agent.test_conversation_migration import migration as previous

    module = migration()
    db = case[0][1]
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE agent_turn"))
        connection.execute(text("DROP TABLE agent_conversation"))
        with Operations.context(MigrationContext.configure(connection)):
            previous().upgrade()
            module.upgrade()
    service, rows, source, scope = arrange(case)
    ticket = enqueue(case, service, rows[0], source, scope)
    db.commit()
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        with pytest.raises(RuntimeError, match="QUEUED"):
            module.downgrade()
        indexes = {row["name"] for row in inspect(connection).get_indexes("agent_turn")}
        assert "ix_agent_turn_queue" in indexes
        connection.execute(
            text("UPDATE agent_turn SET state='FAILED' WHERE id=:id"), {"id": ticket.turn_id}
        )
        module.downgrade()
        assert "ix_agent_turn_queue" not in {
            row["name"] for row in inspect(connection).get_indexes("agent_turn")
        }
        assert connection.scalar(text("SELECT count(*) FROM agent_turn")) == 1
        module.upgrade()
        assert "QUEUED" in inspect(connection).get_check_constraints("agent_turn")[0]["sqltext"]


def test_mysql_offline_queue_ddl_has_check_evolution_and_pool_indexes():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "DROP CHECK ck_agent_turn_state" in ddl
    assert "'QUEUED'" in ddl
    assert "ix_agent_turn_queue" in ddl and "ix_agent_conversation_pool" in ddl
