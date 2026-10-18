"""实际迁移创建的地点覆盖表必须支持 ORM 读取，不能只验证 metadata 建表。"""

import runpy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base
from app.modules.academic.occurrence_location_models import OccurrenceLocationOverride
from sqlalchemy import create_engine, inspect, select, text


def test_location_migration_has_orm_timestamps_and_preserves_override():
    versions = Path(__file__).parents[2] / "migrations/versions"
    location = runpy.run_path(str(versions / "f26a1017s004_occurrence_location.py"))
    repair = runpy.run_path(str(versions / "f26a1018s006_location_timestamps.py"))
    engine = create_engine("sqlite://")
    names = {"occurrence_location_override", "occurrence_location_change"}
    with engine.begin() as db:
        Base.metadata.create_all(
            db, tables=[t for t in Base.metadata.sorted_tables if t.name not in names]
        )
        with Operations.context(MigrationContext.configure(db)):
            location["upgrade"]()
        db.execute(text("INSERT INTO occurrence_location_override "
                        "(occurrence_key,school_id,location,revision,effective_date) "
                        "VALUES ('s:1|2026-10-07',1,'B202',3,'2026-10-07')"))
        with Operations.context(MigrationContext.configure(db)):
            repair["upgrade"]()
        actual = {c["name"] for c in inspect(db).get_columns("occurrence_location_override")}
        assert set(OccurrenceLocationOverride.__table__.columns.keys()) <= actual
        row = db.execute(select(OccurrenceLocationOverride.__table__)).mappings().one()
        assert row["location"] == "B202" and row["revision"] == 3
        assert row["created_at"] is not None and row["updated_at"] is not None
        with Operations.context(MigrationContext.configure(db)):
            repair["downgrade"]()
        row = db.execute(text("SELECT location,revision FROM occurrence_location_override")).one()
        assert row == ("B202", 3)
    engine.dispose()
