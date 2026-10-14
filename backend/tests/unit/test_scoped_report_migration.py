"""Offline round-trip checks for the college ownership report migration."""

import runpy
from io import StringIO
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app import models  # noqa: F401
from app.core.database import Base
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    MetaData,
    PrimaryKeyConstraint,
    create_engine,
    event,
    inspect,
    text,
)

MIGRATION_PATH = (
    Path(__file__).parents[2] / "migrations" / "versions" / "f26a1014r001_scoped_reports.py"
)
MIGRATION = runpy.run_path(str(MIGRATION_PATH))


def _apply(connection, action: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        MIGRATION[action]()


def _create_legacy_schema(connection) -> None:
    old_metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    copied = {
        source.name: source.to_metadata(old_metadata) for source in Base.metadata.sorted_tables
    }

    # Baseline is published e001: college report keys already exist.

    version = copied["report_version"]
    for constraint in list(version.constraints):
        if isinstance(constraint, ForeignKeyConstraint) and any(
            element.parent.name == "college_id_snapshot" for element in constraint.elements
        ):
            version.constraints.remove(constraint)
    version._columns.remove(version.c.college_id_snapshot)

    source_revision = copied["report_source_revision"]
    source_revision.indexes.clear()
    source_revision.constraints.clear()
    source_revision._columns.remove(source_revision.c.ownership_scope_id)
    source_revision.append_constraint(
        PrimaryKeyConstraint("semester_id", "week_no", name="pk_report_source_revision")
    )
    source_revision.append_constraint(
        CheckConstraint("revision >= 0", name="ck_report_source_revision_nonneg")
    )
    source_revision.append_constraint(
        CheckConstraint("week_no >= 1", name="ck_report_source_revision_week")
    )
    source_revision.append_constraint(
        ForeignKeyConstraint(["semester_id"], ["semester.id"], ondelete="RESTRICT")
    )
    old_metadata.create_all(connection)


def _insert_legacy_facts(connection) -> None:
    connection.execute(
        text("""INSERT INTO school
            (id, code, singleton_key, name, lock_version, created_at, updated_at)
            VALUES (910001, 'report-migration-school', 1, 'Migration test', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    )
    connection.execute(
        text("""INSERT INTO college
            (id, school_id, code, name, status, lock_version,
             authorization_revision, configuration_revision, created_at, updated_at)
            VALUES (910001, 910001, 'report-migration-college', 'Migration test',
                    'ACTIVE', 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    )
    connection.execute(
        text("""INSERT INTO semester
            (id, code, name, start_date, end_date, first_monday,
             total_weeks, status, created_at, updated_at)
            VALUES (910001, 'report-migration-semester', 'Migration test',
                    '2026-09-01', '2027-01-31', '2026-09-07', 20, 'ACTIVE',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    )
    connection.execute(
        text("""INSERT INTO report
            (id, semester_id, week_no, scope, latest_version_no,
             created_at, updated_at)
            VALUES (910001, 910001, 1, 'COLLEGE', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    )
    connection.execute(
        text("""INSERT INTO report_version
            (id, report_id, version_no, source_revision, rule_version,
             template_version, status, created_at)
            VALUES (910001, 910001, 1, 7, 1, 1, 'PUBLISHED', CURRENT_TIMESTAMP)""")
    )
    connection.execute(
        text("""INSERT INTO report_source_revision
            (semester_id, week_no, revision, updated_at)
            VALUES (910001, 1, 7, CURRENT_TIMESTAMP)""")
    )


def _sqlite_engine():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    return engine


def _report_facts(connection):
    return connection.execute(
        text("SELECT id, semester_id, week_no, scope FROM report ORDER BY id")
    ).all()


def test_upgrade_and_downgrade_preserve_legacy_report_facts_and_match_models():
    engine = _sqlite_engine()
    try:
        with engine.begin() as connection:
            _create_legacy_schema(connection)
            _insert_legacy_facts(connection)
            _apply(connection, "upgrade")

            assert connection.execute(
                text("SELECT id, scope_college_key FROM report WHERE id=910001")
            ).one() == (910001, 0)
            assert connection.execute(
                text("SELECT id, college_id_snapshot FROM report_version ORDER BY id")
            ).all() == [(910001, None)]
            assert connection.execute(
                text("SELECT ownership_scope_id, revision FROM report_source_revision")
            ).one() == (0, 7)
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

            _apply(connection, "downgrade")
            assert _report_facts(connection) == [(910001, 910001, 1, "COLLEGE")]
            assert connection.execute(text("SELECT id, version_no FROM report_version")).one() == (
                910001,
                1,
            )
            assert connection.execute(
                text("SELECT semester_id, week_no, revision FROM report_source_revision")
            ).one() == (910001, 1, 7)
            assert "ownership_scope_id" not in {
                column["name"] for column in inspect(connection).get_columns("report")
            }
    finally:
        engine.dispose()


def test_downgrade_refuses_multiple_college_reports_without_changing_facts():
    engine = _sqlite_engine()
    try:
        with engine.begin() as connection:
            _create_legacy_schema(connection)
            _insert_legacy_facts(connection)
            _apply(connection, "upgrade")
            connection.execute(
                text("""INSERT INTO report
                    (id, semester_id, week_no, scope, college_id, ownership_version,
                     latest_version_no, created_at, updated_at)
                    VALUES (910002, 910001, 1, 'COLLEGE', 910001, 1, 0,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
            )
            before = _report_facts(connection)
            before_sources = connection.execute(
                text(
                    "SELECT ownership_scope_id, semester_id, week_no, revision "
                    "FROM report_source_revision ORDER BY ownership_scope_id"
                )
            ).all()

            try:
                _apply(connection, "downgrade")
            except RuntimeError as exc:
                assert "多学院" in str(exc)
            else:
                raise AssertionError("downgrade unexpectedly accepted duplicate weekly reports")

            assert _report_facts(connection) == before
            assert (
                connection.execute(
                    text(
                        "SELECT ownership_scope_id, semester_id, week_no, revision "
                        "FROM report_source_revision ORDER BY ownership_scope_id"
                    )
                ).all()
                == before_sources
            )
            assert "scope_college_key" in {
                column["name"] for column in inspect(connection).get_columns("report")
            }
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_compile_mysql_offline_ddl():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        MIGRATION["upgrade"]()
    upgrade_sql = output.getvalue().lower()
    assert "alter table report " not in upgrade_sql
    assert "ownership_scope_id" in upgrade_sql
    assert "fk_report_version_college_snapshot" in upgrade_sql
    assert "primary key (ownership_scope_id, semester_id, week_no)" in upgrade_sql
    assert upgrade_sql.index(
        "create index ix_report_source_revision_semester_id"
    ) < upgrade_sql.index("drop primary key")

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        MIGRATION["downgrade"]()
    downgrade_sql = output.getvalue().lower()
    assert "delete from report_source_revision where ownership_scope_id <> 0" in downgrade_sql
    assert "alter table report " not in downgrade_sql
    assert "drop foreign key fk_report_version_college_snapshot" in downgrade_sql
