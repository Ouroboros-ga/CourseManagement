"""A refused downgrade must leave schema intact, including after reactivation."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_withdrawal_history_refuses_downgrade_before_any_schema_change(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "migrations/versions/f26a1022e001_attendance_effect_state.py"
    spec = importlib.util.spec_from_file_location("effect_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    records = sa.Table(
        "attendance_record", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("effect_state", sa.String(16)),
        sa.CheckConstraint("effect_state IN ('EFFECTIVE','WITHDRAWN')", name="ck_attendance_record_effect_state"),
        sa.Index("ix_attendance_record_effect_state", "effect_state"),
    )
    versions = sa.Table(
        "attendance_record_version", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_type", sa.String(16)),
    )
    metadata.create_all(engine)
    with engine.connect() as connection:
        connection.execute(records.insert().values(id=1, effect_state="EFFECTIVE"))
        connection.execute(versions.insert().values(id=1, source_type="WITHDRAWAL"))
        connection.commit()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="撤回版本"):
            migration.downgrade()
        inspector = sa.inspect(connection)
        assert "effect_state" in {column["name"] for column in inspector.get_columns("attendance_record")}
        assert "ix_attendance_record_effect_state" in {index["name"] for index in inspector.get_indexes("attendance_record")}
    engine.dispose()
