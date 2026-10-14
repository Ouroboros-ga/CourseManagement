"""t001/g001 SQLite round-trip and MySQL offline DDL checks."""

import runpy
from io import StringIO
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app import models  # noqa: F401
from app.core.database import Base
from sqlalchemy import ForeignKeyConstraint, create_engine, event, inspect, text

MIGRATIONS = Path(__file__).parents[2] / "migrations" / "versions"
REVISIONS = (
    "f26a1014t001_college_time.py",
    "f26a1014g001_group_business.py",
    "f26a1014x001_teaching_type_ownership.py",
)
NEW_TABLES = {
    "college_time_version",
    "volunteer_group_member",
    "volunteer_group_support",
}
NEW_COLUMNS = {
    "inspection_task": {
        "activity_start_at",
        "activity_end_at",
        "time_snapshot",
        "group_id",
        "group_config_version_id",
        "group_name_snapshot",
        "course_type_id_snapshot",
        "course_type_name_snapshot",
        "classification_revision_snapshot",
    },
    "teaching_class": {"course_type_id", "classification_revision"},
}


def _migration(filename: str) -> dict:
    return runpy.run_path(str(MIGRATIONS / filename))


def _apply(connection, migration: dict, action: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration[action]()


def _create_pre_migration_schema(connection) -> None:
    metadata = Base.metadata
    # Build one consistent copied MetaData while omitting migration-owned schema.
    # Table.to_metadata resolves FKs into its destination metadata, so recreate
    # all tables into one metadata before removing the added columns.
    from sqlalchemy import MetaData

    old_metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    copied = {
        source.name: source.to_metadata(old_metadata)
        for source in metadata.sorted_tables
        if source.name not in NEW_TABLES
    }
    for table in copied.values():
        removed = NEW_COLUMNS.get(table.name, set())
        for constraint in list(table.constraints):
            if isinstance(constraint, ForeignKeyConstraint) and any(
                element.parent.name in removed
                or element.target_fullname.split(".")[0] in NEW_TABLES
                for element in constraint.elements
            ):
                table.constraints.remove(constraint)
        for index in list(table.indexes):
            if any(column.name in removed for column in index.columns):
                table.indexes.remove(index)
        for column_name in removed:
            if column_name in table.c:
                table._columns.remove(table.c[column_name])
    old_metadata.create_all(connection)


def test_college_group_migrations_round_trip_and_match_models():
    migrations = [_migration(filename) for filename in REVISIONS]
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    try:
        with engine.begin() as connection:
            _create_pre_migration_schema(connection)
            before_tables = set(inspect(connection).get_table_names())
            assert not NEW_TABLES & before_tables
            assert not NEW_COLUMNS["inspection_task"] & {
                column["name"] for column in inspect(connection).get_columns("inspection_task")
            }
            assert not NEW_COLUMNS["teaching_class"] & {
                column["name"] for column in inspect(connection).get_columns("teaching_class")
            }

            for migration in migrations:
                _apply(connection, migration, "upgrade")

            connection.execute(
                text("""INSERT INTO school
                    (id, code, singleton_key, name, lock_version, created_at, updated_at)
                    VALUES (910001, 'migration-test-school', 1, 'Migration test', 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
            )
            connection.execute(
                text("""INSERT INTO college
                    (id, school_id, code, name, status, lock_version,
                     authorization_revision, configuration_revision, created_at, updated_at)
                    VALUES (910001, 910001, 'migration-test-college', 'Migration test',
                            'ACTIVE', 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
            )
            connection.execute(
                text("""INSERT INTO semester
                    (id, code, name, start_date, end_date, first_monday,
                     total_weeks, status, created_at, updated_at)
                    VALUES (910001, 'migration-test-semester', 'Migration test',
                            '2026-09-01', '2027-01-31', '2026-09-07', 20, 'ACTIVE',
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
            )
            # Insert an old-format task after upgrade so SQLite batch table
            # rebuilds do not need to rewrite a row with a task child reference.
            connection.execute(
                text("""INSERT INTO inspection_task
                    (id, task_key, semester_id, inspection_date, week_no,
                     inspection_type, start_period, end_period,
                     expected_count_snapshot, expected_count_current,
                     roster_version, lock_version, created_at, updated_at)
                    VALUES (910001, 'migration-legacy-task', 910001, '2026-09-01', 1,
                            'COURSE', 1, 2, 0, 0, 1, 0,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
            )
            context = MigrationContext.configure(connection)
            differences = compare_metadata(context, Base.metadata)
            assert differences == []

            for migration in reversed(migrations):
                _apply(connection, migration, "downgrade")

            inspector = inspect(connection)
            after_tables = set(inspector.get_table_names())
            assert not NEW_TABLES & after_tables
            assert before_tables == after_tables
            assert not NEW_COLUMNS["inspection_task"] & {
                column["name"] for column in inspector.get_columns("inspection_task")
            }
            assert not NEW_COLUMNS["teaching_class"] & {
                column["name"] for column in inspector.get_columns("teaching_class")
            }
            assert (
                connection.execute(
                    text("SELECT task_key FROM inspection_task WHERE id=910001")
                ).scalar_one()
                == "migration-legacy-task"
            )
    finally:
        engine.dispose()


def test_college_group_migrations_compile_mysql_offline_ddl():
    migrations = [_migration(filename) for filename in REVISIONS]
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        for migration in migrations:
            migration["upgrade"]()
    upgrade_sql = output.getvalue()
    assert "CREATE TABLE college_time_version" in upgrade_sql
    assert "CREATE TABLE volunteer_group_member" in upgrade_sql
    assert "CREATE TABLE volunteer_group_support" in upgrade_sql
    for name in NEW_COLUMNS["inspection_task"] | NEW_COLUMNS["teaching_class"]:
        assert name in upgrade_sql
    assert "fk_teaching_class_course_type" in upgrade_sql
    assert "fk_inspection_task_group" in upgrade_sql
    assert "fk_inspection_task_group_config" in upgrade_sql

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        for migration in reversed(migrations):
            migration["downgrade"]()
    downgrade_sql = output.getvalue()
    assert "DROP TABLE volunteer_group_support" in downgrade_sql
    assert "DROP TABLE volunteer_group_member" in downgrade_sql
    assert "DROP TABLE college_time_version" in downgrade_sql
    assert "classification_revision" in downgrade_sql
    assert "time_snapshot" in downgrade_sql
