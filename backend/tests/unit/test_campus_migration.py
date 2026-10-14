"""冻结迁移与 ORM 的离线对账，不连接运行 MySQL。"""

import runpy
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app import models  # noqa: F401
from app.core.database import Base
from sqlalchemy import create_engine, event, inspect

NEW_TABLES = {
    "school",
    "college",
    "scoped_grant",
    "course_type",
    "volunteer_group",
    "group_config_version",
    "group_scope_type",
}


def test_configuration_migration_round_trip_matches_metadata():
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "migrations/versions/f26a1013c001_campus_configuration.py")
    )
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in NEW_TABLES:
                table.create(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        assert set(inspect(connection).get_table_names()) >= NEW_TABLES
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            migration["downgrade"]()
        assert not NEW_TABLES & set(inspect(connection).get_table_names())
        assert "user_account" in inspect(connection).get_table_names()
    engine.dispose()


def test_ownership_migration_preserves_legacy_rows_and_round_trips():
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "migrations/versions/f26a1013c002_business_ownership.py")
    )
    old = sa.MetaData(naming_convention=Base.metadata.naming_convention)
    for table in Base.metadata.sorted_tables:
        table.to_metadata(old)
    for name in migration["TABLES"]:
        table = old.tables[name]
        column = table.c.college_id
        for constraint in list(table.constraints):
            if (
                isinstance(constraint, sa.ForeignKeyConstraint)
                and column.name in constraint.columns
            ):
                table.constraints.remove(constraint)
                for fk in constraint.elements:
                    table.foreign_keys.discard(fk)
        for index in list(table.indexes):
            if column.name in index.columns:
                table.indexes.remove(index)
        table._columns.remove(column)
        table._columns.remove(table.c.ownership_version)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        old.create_all(connection)
        from app.core.database import utcnow

        connection.execute(
            old.tables["administrative_class"]
            .insert()
            .values(
                id=1,
                class_code="OLD",
                class_name="保留旧班",
                college="未确认文本",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        row = connection.execute(
            sa.text("SELECT college_id, ownership_version, college FROM administrative_class")
        ).one()
        assert row == (None, 1, "未确认文本")
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            migration["downgrade"]()
        assert "college_id" not in {
            c["name"] for c in inspect(connection).get_columns("administrative_class")
        }
        assert (
            connection.scalar(sa.text("SELECT class_name FROM administrative_class WHERE id=1"))
            == "保留旧班"
        )
    engine.dispose()
