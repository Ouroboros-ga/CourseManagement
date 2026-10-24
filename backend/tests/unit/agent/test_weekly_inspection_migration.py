import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import Base
from sqlalchemy import inspect, text
from tests.unit.agent.test_weekly_inspection import arrange, fixture  # noqa: F401


def migration():
    path = Path(__file__).parents[3] / "migrations/versions/f26a1025a014_weekly_inspection.py"
    spec = importlib.util.spec_from_file_location("weekly_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_matches_models_and_nonempty_downgrade_preserves_both_tables(case):
    db = case[0]
    db.commit()
    module = migration()
    names = ["weekly_inspection_execution", "weekly_inspection_plan"]
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for name in names:
            connection.execute(text(f"DROP TABLE {name}"))
        module.upgrade()
        for name in names:
            assert {column["name"] for column in inspect(connection).get_columns(name)} == set(
                Base.metadata.tables[name].columns.keys()
            )
        module.downgrade()
        module.upgrade()
    service, body = arrange(case)
    service.save(case[1], body)
    with db.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="history"):
            module.downgrade()
        assert set(names) <= set(inspect(connection).get_table_names())


def test_mysql_offline_has_week_unique_identity_and_restrict_history_bindings():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration().upgrade()
    ddl = output.getvalue()
    assert "DATETIME(3)" in ddl and "utf8mb4_0900_ai_ci" in ddl
    assert "uq_weekly_execution_week UNIQUE (plan_id, target_week)" in ddl
    assert (
        "FOREIGN KEY(assignment_plan_id) REFERENCES "
        "assignment_confirmation_plan (id) ON DELETE RESTRICT" in ddl
    )
    assert "ix_weekly_plan_due" in ddl and "ix_weekly_execution_state" in ddl
