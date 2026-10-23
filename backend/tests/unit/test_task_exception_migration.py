import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_rows_and_refuses_lossy_downgrade():
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "migrations/versions/f26a1023x001_task_exception.py")
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE user_account (id BIGINT PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE inspection_task (id BIGINT PRIMARY KEY)")
        db.exec_driver_sql(
            "CREATE TABLE task_roster_member (id BIGINT PRIMARY KEY, "
            "task_id BIGINT REFERENCES inspection_task(id), name TEXT)"
        )
        db.exec_driver_sql(
            "CREATE TABLE task_deadline_assessment (id BIGINT PRIMARY KEY, "
            "task_id BIGINT REFERENCES inspection_task(id), result VARCHAR(32), "
            "CONSTRAINT ck_task_deadline_assessment_result "
            "CHECK (result IN ('VALID_SUBMISSION','OVERDUE_UNEXECUTED','CANCELED')))"
        )
        db.exec_driver_sql("INSERT INTO inspection_task VALUES (1)")
        db.exec_driver_sql("INSERT INTO task_roster_member VALUES (1,1,'preserve')")
        db.exec_driver_sql("INSERT INTO task_deadline_assessment VALUES (1,1,'OVERDUE_UNEXECUTED')")
        with Operations.context(MigrationContext.configure(db)):
            migration["upgrade"]()
            assert db.exec_driver_sql("SELECT name FROM task_roster_member").scalar() == "preserve"
            assert (
                db.exec_driver_sql("SELECT result FROM task_deadline_assessment").scalar()
                == "OVERDUE_UNEXECUTED"
            )
            db.exec_driver_sql("UPDATE task_deadline_assessment SET result='EXCEPTION'")
            with pytest.raises(RuntimeError):
                migration["downgrade"]()
            assert "exception_reported_at" in {
                c["name"] for c in sa.inspect(db).get_columns("inspection_task")
            }
            db.exec_driver_sql("UPDATE task_deadline_assessment SET result='OVERDUE_UNEXECUTED'")
            db.exec_driver_sql(
                "UPDATE inspection_task SET exception_reported_at='2026-10-23 10:00:00'"
            )
            with pytest.raises(RuntimeError):
                migration["downgrade"]()
            db.exec_driver_sql("UPDATE inspection_task SET exception_reported_at=NULL")
            migration["downgrade"]()
            assert db.exec_driver_sql("SELECT name FROM task_roster_member").scalar() == "preserve"
    engine.dispose()
