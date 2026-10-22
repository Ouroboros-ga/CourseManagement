"""Refusal must preserve MySQL schema after withdrawal followed by resubmission."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def test_withdrawal_version_refuses_downgrade_without_partial_ddl(engine, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "migrations/versions/f26a1022e001_attendance_effect_state.py"
    spec = importlib.util.spec_from_file_location("mysql_effect_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Integration engine has already passed both *_test isolation guards. Synthetic
    # anchors only exercise schema refusal; no business database can reach this fixture.
    with engine.connect() as connection:
        connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            connection.execute(text(
                "INSERT INTO attendance_record "
                "(id,task_id,student_id,effective_type,effect_state,current_version,created_at) "
                "VALUES (1,1,1,'ABSENT','EFFECTIVE',3,NOW(3))"
            ))
            connection.execute(text(
                "INSERT INTO attendance_record_version "
                "(attendance_record_id,version_no,attendance_type,source_type,changed_by,created_at) "
                "VALUES (1,2,'ABSENT','WITHDRAWAL',1,NOW(3))"
            ))
            connection.commit()
        finally:
            connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        before = connection.execute(text("SHOW CREATE TABLE attendance_record")).one()[1]
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="撤回版本"):
            migration.downgrade()
        after = connection.execute(text("SHOW CREATE TABLE attendance_record")).one()[1]
        assert after == before
        assert "effect_state" in {column["name"] for column in inspect(connection).get_columns("attendance_record")}
