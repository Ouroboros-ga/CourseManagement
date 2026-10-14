"""冻结发布/私人副本迁移的离线升降与元数据对账，不访问运行数据库。"""

import runpy
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app import models  # noqa: F401
from app.core.database import Base
from sqlalchemy import create_engine, event, inspect

TABLES = {
    "academic_publication",
    "published_schedule",
    "published_schedule_student",
    "publication_audience",
    "personal_timetable",
}


def test_publication_migration_matches_models_and_preserves_business_tables():
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "migrations/versions/f26a1014p001_academic_publication.py")
    )
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in TABLES:
                table.create(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            migration["downgrade"]()
        assert not TABLES & set(inspect(connection).get_table_names())
        assert {"course_schedule", "student", "inspection_task"} <= set(
            inspect(connection).get_table_names()
        )
    engine.dispose()
