"""名单归属迁移必须能够在真实 InnoDB 外键约束下回退并重建。"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


def test_roster_provenance_downgrade_keeps_foreign_key_indexes_valid(engine, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "migrations/versions"
    spec = importlib.util.spec_from_file_location(
        "staff_provenance_migration", path / "f26a1017s005_roster_teaching_provenance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        assert inspect(connection).has_table("task_roster_member_class")
        module.downgrade()
        assert not inspect(connection).has_table("task_roster_member_class")
        module.upgrade()
        assert inspect(connection).has_table("task_roster_member_class")
        assert len(inspect(connection).get_foreign_keys("task_roster_member_class")) == 3
        connection.commit()
