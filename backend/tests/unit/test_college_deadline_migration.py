import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_deadline_migration_preserves_existing_children_and_refuses_lossy_downgrade():
    path = Path(__file__).parents[2] / "migrations/versions/f26a1015d001_college_deadlines.py"
    migration = runpy.run_path(str(path))
    engine = sa.create_engine("sqlite://")
    sa.event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE semester (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql(
            "CREATE TABLE submission_deadline_day (id INTEGER PRIMARY KEY, semester_id INTEGER REFERENCES semester(id), inspection_date DATE, deadline_at DATETIME, version INTEGER, CONSTRAINT uq_submission_deadline_day_sem_date UNIQUE(semester_id, inspection_date))"
        )
        db.exec_driver_sql(
            "CREATE TABLE inspection_task (id INTEGER PRIMARY KEY, semester_id INTEGER REFERENCES semester(id))"
        )
        db.exec_driver_sql(
            "CREATE TABLE task_roster_version (id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES inspection_task(id), value TEXT)"
        )
        db.exec_driver_sql(
            "CREATE TABLE submission_deadline_version (id INTEGER PRIMARY KEY, deadline_day_id INTEGER REFERENCES submission_deadline_day(id), value TEXT)"
        )
        db.exec_driver_sql("INSERT INTO semester VALUES (1)")
        db.exec_driver_sql(
            "INSERT INTO submission_deadline_day VALUES (1, 1, '2026-10-15', '2026-10-15 14:00:00', 1)"
        )
        db.exec_driver_sql("INSERT INTO inspection_task VALUES (1, 1)")
        db.exec_driver_sql("INSERT INTO task_roster_version VALUES (1, 1, 'preserve roster')")
        db.exec_driver_sql(
            "INSERT INTO submission_deadline_version VALUES (1, 1, 'preserve deadline')"
        )
        with Operations.context(MigrationContext.configure(db)):
            migration["upgrade"]()
            assert (
                db.exec_driver_sql(
                    "SELECT ownership_scope_id FROM submission_deadline_day"
                ).scalar()
                == 0
            )
            assert (
                db.exec_driver_sql("SELECT deadline_day_id FROM inspection_task").scalar() is None
            )
            assert (
                db.exec_driver_sql("SELECT value FROM task_roster_version").scalar()
                == "preserve roster"
            )
            assert (
                db.exec_driver_sql("SELECT value FROM submission_deadline_version").scalar()
                == "preserve deadline"
            )
            db.exec_driver_sql(
                "INSERT INTO submission_deadline_day (id, semester_id, inspection_date, deadline_at, version, ownership_scope_id) VALUES (2, 1, '2026-10-15', '2026-10-15 13:00:00', 1, 2)"
            )
            with pytest.raises(RuntimeError):
                migration["downgrade"]()
            assert "deadline_day_id" in {
                c["name"] for c in sa.inspect(db).get_columns("inspection_task")
            }
            db.exec_driver_sql("DELETE FROM submission_deadline_day WHERE id=2")
            migration["downgrade"]()
        assert (
            db.exec_driver_sql("SELECT value FROM task_roster_version").scalar()
            == "preserve roster"
        )
        assert (
            db.exec_driver_sql("SELECT value FROM submission_deadline_version").scalar()
            == "preserve deadline"
        )
    engine.dispose()
