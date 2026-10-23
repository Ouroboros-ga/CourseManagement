"""Clone schema only into a disposable *_test DB; rehearse DDL and run real MySQL regressions."""
import json
import os
import secrets
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.modules.academic.models import Semester
from app.modules.inspection.models import InspectionTask, TaskDeadlineAssessment, TaskRosterVersion

HEAD = "f26a1023x001"
PREVIOUS = "f26a1022e001"
TESTS = [
    "test_task_exception", "test_task_exception_migration", "test_exception_mysql_concurrency",
    "test_change_request_workbench", "test_scoped_assignment_requests",
    "test_assignment_confirmation_plan", "test_group_submission", "test_college_deadlines",
    "test_list_pagination", "test_staff_records", "test_scoped_reports",
    "test_report_submission_validity", "test_submission_correction_window",
]


def root_sql(statement, database=None):
    command = ["docker", "exec", "-i", "course-management-mysql", "mysql",
               "--defaults-extra-file=/run/cm-root.cnf"]
    if database:
        assert database.endswith("_test")
        command.append(database)
    result = subprocess.run(command, input=statement, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Isolated MySQL setup/cleanup failed")
    return result.stdout


def main():
    logs = Path(sys.argv[1]).resolve()
    assert logs.is_dir()
    config = Settings(_env_file="/etc/course-management/backend.env")
    original = make_url(config.database_url)
    assert original.database == "course_management"
    suffix = secrets.token_hex(6)
    database, user, password = "cm_inspection_" + suffix + "_test", "inspqa_" + suffix, secrets.token_hex(24)
    assert database.endswith("_test") and database != original.database
    url = original.set(username=user, password=password, database=database)
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False),
           "CAMPUS_TEST_DATABASE_URL": url.render_as_string(hide_password=False)}
    engine = None
    def alembic(action, revision, *, fails=False):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision],
                                env=env, text=True, capture_output=True)
        with (logs / "migration-rehearsal.log").open("a") as log:
            log.write(result.stdout + result.stderr)
        assert (result.returncode != 0) if fails else (result.returncode == 0), "Migration rehearsal failed"
    try:
        root_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
                 f"CREATE USER '{user}'@'%' IDENTIFIED BY '{password}'; "
                 f"GRANT ALL ON `{database}`.* TO '{user}'@'%';")
        dump = subprocess.run(["docker", "exec", "course-management-mysql", "mysqldump",
            "--defaults-extra-file=/run/cm-root.cnf", "--no-data", "--skip-triggers",
            "--no-tablespaces", "--set-gtid-purged=OFF", "course_management"],
            capture_output=True, text=True, check=True).stdout
        assert "USE `course_management`" not in dump and "CREATE DATABASE" not in dump
        root_sql(dump, database)
        engine = create_engine(url)
        with engine.begin() as con:
            assert con.scalar(text("SELECT version_num FROM alembic_version")) is None
            con.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": PREVIOUS})
            sem = con.execute(Semester.__table__.insert().values(code="ISOLATED-QA", name="synthetic",
                start_date=date(2026, 9, 1), end_date=date(2027, 1, 31), first_monday=date(2026, 8, 31),
                total_weeks=20, status="ACTIVE")).inserted_primary_key[0]
            task_id = con.execute(InspectionTask.__table__.insert().values(task_key="isolated-migration",
                semester_id=sem, inspection_date=date(2026, 9, 7), week_no=2,
                inspection_type="COURSE", start_period=1, end_period=2,
                course_name_snapshot="synthetic", expected_count_current=21)).inserted_primary_key[0]
            con.execute(TaskRosterVersion.__table__.insert().values(task_id=task_id, version_no=1,
                                                                   reason="preserve synthetic roster"))
            con.execute(TaskDeadlineAssessment.__table__.insert().values(task_id=task_id,
                result="OVERDUE_UNEXECUTED", deadline_at_snapshot=datetime(2026, 9, 7, 14),
                evaluated_at=datetime(2026, 9, 7, 15)))
        alembic("upgrade", HEAD)
        with engine.connect() as con:
            assert con.scalar(text("SELECT expected_count_current FROM inspection_task")) == 21
            assert con.scalar(text("SELECT reason FROM task_roster_version")) == "preserve synthetic roster"
            assert con.scalar(text("SELECT result FROM task_deadline_assessment")) == "OVERDUE_UNEXECUTED"
        alembic("downgrade", PREVIOUS)
        assert "exception_reported_at" not in {c["name"] for c in inspect(engine).get_columns("inspection_task")}
        alembic("upgrade", HEAD)
        with engine.begin() as con:
            con.execute(text("UPDATE inspection_task SET exception_reported_at='2026-10-23 01:00:00'"))
        alembic("downgrade", PREVIOUS, fails=True)
        with engine.begin() as con:
            assert con.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            con.execute(text("UPDATE inspection_task SET exception_reported_at=NULL"))
            con.execute(text("UPDATE task_deadline_assessment SET result='EXCEPTION'"))
        alembic("downgrade", PREVIOUS, fails=True)
        with engine.begin() as con:
            con.execute(text("UPDATE task_deadline_assessment SET result='OVERDUE_UNEXECUTED'"))
        alembic("downgrade", PREVIOUS)
        alembic("upgrade", HEAD)
        engine.dispose()
        result = subprocess.run([sys.executable, "-m", "pytest",
            *["tests/unit/" + name + ".py" for name in TESTS], "-q", "-p", "no:cacheprovider"],
            env=env, text=True, capture_output=True)
        (logs / "mysql-acceptance.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, "Isolated MySQL regression failed; inspect protected QA log"
        assert "63 passed" in result.stdout and "skipped" not in result.stdout
        print(json.dumps({"migration_upgrade":True, "synthetic_history_preserved":True,
            "downgrade_round_trip":True, "lossy_downgrade_refused":True,
            "mysql_tests_passed":63, "concurrency_tests_passed":2}))
    finally:
        if engine is not None:
            engine.dispose()
        root_sql(f"DROP DATABASE IF EXISTS `{database}`; DROP USER IF EXISTS '{user}'@'%';")


if __name__ == "__main__":
    main()
