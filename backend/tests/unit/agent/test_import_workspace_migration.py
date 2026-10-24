import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import Base
from sqlalchemy import inspect, text


def migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1025a012_import_workspace.py"
    assert path.exists(), "Import workspace migration is missing"
    spec = importlib.util.spec_from_file_location("import_workspace_migration", path)
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


def test_upgrade_schema_and_nonempty_downgrade_guard(case):
    from tests.unit.agent.test_import_workspace import arrange, upload

    module = migration()
    db = case[0][1]
    db.commit()
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        connection.execute(text("DROP TABLE agent_import_workspace"))
        module.upgrade()
        assert {
            c["name"] for c in inspect(connection).get_columns("agent_import_workspace")
        } == set(Base.metadata.tables["agent_import_workspace"].columns.keys())
        module.downgrade()
        module.upgrade()
    service, _, scope = arrange(case)
    upload(service, scope)
    db.commit()
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="agent_import_workspace"):
            module.downgrade()
        assert connection.scalar(text("SELECT count(*) FROM agent_import_workspace")) == 1


def test_mysql_offline_ddl_has_private_file_binding_and_queue_indexes():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE agent_import_workspace" in ddl and "DATETIME(3)" in ddl
    assert "FOREIGN KEY(file_id) REFERENCES file_object (id) ON DELETE RESTRICT" in ddl
    assert "uq_agent_import_request" in ddl and "ix_agent_import_queue" in ddl
    assert "utf8mb4_0900_ai_ci" in ddl
