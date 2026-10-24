"""Check MySQL rollback DDL ordering without pretending to execute a real migration."""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize(
    "name,foreign,index",
    [
        (
            "f26a1024a004_change_identity.py",
            "fk_agent_run_change_execution",
            "uq_agent_run_change_execution",
        ),
        (
            "f26a1024a008_objection_identity.py",
            "fk_agent_run_objection_job",
            "uq_agent_run_objection_job",
        ),
        (
            "f26a1024a009_precheck_retries.py",
            "fk_precheck_retry_parent",
            "uq_precheck_retry_parent",
        ),
    ],
)
def test_empty_history_mysql_downgrade_removes_fk_before_its_supporting_index(
    monkeypatch, name, foreign, index
):
    path = Path(__file__).parents[3] / "migrations/versions" / name
    spec = importlib.util.spec_from_file_location("tested_downgrade", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class EmptyHistory:
        def execute(self, statement):
            return self

        def first(self):
            return None

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        monkeypatch.setattr(migration.op, "get_bind", lambda: EmptyHistory())
        migration.downgrade()
    sql = output.getvalue()
    assert sql.index(f"DROP FOREIGN KEY {foreign}") < sql.index(f"DROP INDEX {index}")
