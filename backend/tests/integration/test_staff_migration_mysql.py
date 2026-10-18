"""名单归属迁移必须能够在真实 InnoDB 外键约束下回退并重建。"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.academic.occurrence_location_models import OccurrenceLocationOverride
from app.modules.organization.models import School
from sqlalchemy import inspect, select, text


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


def test_location_timestamp_repair_preserves_existing_override_on_mysql(engine, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "migrations/versions"
    spec = importlib.util.spec_from_file_location(
        "location_timestamp_migration", path / "f26a1018s006_location_timestamps.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as connection:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.downgrade()
        connection.execute(School.__table__.insert().values(id=1, code="CM", name="迁移测试"))
        connection.execute(text(
            "INSERT INTO occurrence_location_override "
            "(occurrence_key,school_id,location,revision,effective_date) "
            "VALUES ('s:1|2026-10-07',1,'B202',3,'2026-10-07')"
        ))
        module.upgrade()
        row = connection.execute(select(OccurrenceLocationOverride.__table__)).mappings().one()
        assert row["location"] == "B202" and row["revision"] == 3
        assert row["created_at"] is not None and row["updated_at"] is not None
        connection.commit()
