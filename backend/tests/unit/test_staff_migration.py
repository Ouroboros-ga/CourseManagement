"""新增表迁移与 ORM 对齐；离线 SQLite 演练不代表 MySQL 锁行为验收。"""

import runpy
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base
from sqlalchemy import create_engine, inspect


def test_staff_migration_matches_models_and_does_not_change_existing_tables():
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "migrations/versions/f26a1017s001_staff_foundation.py")
    )
    new_names = {"faculty_staff", "teaching_staff_assignment", "class_staff_responsibility"}
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        Base.metadata.create_all(
            db, tables=[t for t in Base.metadata.sorted_tables if t.name not in new_names]
        )
        before = set(inspect(db).get_table_names())
        with Operations.context(MigrationContext.configure(db)):
            migration["upgrade"]()
        assert set(inspect(db).get_table_names()) == before | new_names
        assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
        with Operations.context(MigrationContext.configure(db)):
            migration["downgrade"]()
        assert set(inspect(db).get_table_names()) == before
    engine.dispose()
