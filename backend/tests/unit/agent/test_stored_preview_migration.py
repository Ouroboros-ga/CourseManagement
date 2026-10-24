import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import Base
from sqlalchemy import inspect, text


def migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1025a013_stored_previews.py"
    spec = importlib.util.spec_from_file_location("stored_preview_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_import_workspace import fixture as workspace_fixture

    original = workspace_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def test_schema_upgrade_roundtrip_and_guard_before_destructive_ddl(case):
    from tests.unit.agent.test_import_workspace import arrange, upload
    from tests.unit.agent.test_import_workspace_migration import migration as previous

    db = case[0][1]
    db.commit()
    module = migration()
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        connection.execute(text("DROP TABLE agent_import_workspace"))
        previous().upgrade()
        module.upgrade()
        assert {
            c["name"] for c in inspect(connection).get_columns("agent_import_workspace")
        } == set(Base.metadata.tables["agent_import_workspace"].columns.keys())
        module.downgrade()
        module.upgrade()
    service, _, scope = arrange(case)
    record = upload(service, scope)
    db.commit()
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        connection.execute(
            text(
                "UPDATE agent_import_workspace SET preview_json = :receipt, "
                "state = 'PREVIEW_PROCESSING' WHERE id = :wid"
            ),
            {"receipt": '{"current":{"status":"RUNNING"}}', "wid": int(record["workspace_id"])},
        )
        with pytest.raises(RuntimeError, match="preview receipts"):
            module.downgrade()
        assert "preview_json" in {
            c["name"] for c in inspect(connection).get_columns("agent_import_workspace")
        }
        assert (
            connection.scalar(text("SELECT state FROM agent_import_workspace"))
            == "PREVIEW_PROCESSING"
        )


def test_mysql_offline_upgrade_keeps_history_and_expands_queue_state():
    output = StringIO()
    with Operations.context(
        MigrationContext.configure(
            dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
        )
    ):
        migration().upgrade()
    ddl = output.getvalue()
    assert "ADD COLUMN preview_json JSON" in ddl
    assert "VARCHAR(24)" in ddl and "PREVIEW_PROCESSING" in ddl
    assert "DROP TABLE" not in ddl
