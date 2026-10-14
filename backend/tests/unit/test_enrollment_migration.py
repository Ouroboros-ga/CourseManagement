"""Frozen m001 schema exercises e001; never reads production credentials/data."""

import runpy
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import utcnow
from app.models import Base


def test_enrollment_upgrade_preserves_current_identity_and_matches_models():
    engine = sa.create_engine("sqlite://")
    schema = (Path(__file__).parents[1] / "fixtures/campus_m001_schema.sql").read_text(
        encoding="utf-8"
    )
    with engine.connect() as db:
        db.connection.driver_connection.executescript(schema)
        meta = sa.MetaData()
        meta.reflect(db)
        t = meta.tables
        stamp = dict(created_at=utcnow(), updated_at=utcnow())
        db.execute(
            t["school"]
            .insert()
            .values(id=1, code="S", name="学校", singleton_key=1, lock_version=1, **stamp)
        )
        db.execute(
            t["college"]
            .insert()
            .values(
                id=1,
                school_id=1,
                code="C",
                name="学院",
                status="ACTIVE",
                lock_version=1,
                authorization_revision=1,
                configuration_revision=1,
                **stamp,
            )
        )
        db.execute(
            t["administrative_class"]
            .insert()
            .values(id=1, class_code="C1", class_name="一班", college_id=1, **stamp)
        )
        db.execute(
            t["student"]
            .insert()
            .values(id=1, student_no="0001", name="学生", administrative_class_id=1, **stamp)
        )
        db.execute(t["role"].insert().values(id=1, code="TEACHER_ADMIN", name="教师", **stamp))
        db.execute(
            t["user_account"]
            .insert()
            .values(id=1, username="teacher", display_name="老师", status="ACTIVE", **stamp)
        )
        db.execute(t["user_role"].insert().values(user_id=1, role_id=1))
        db.execute(
            t["scoped_grant"]
            .insert()
            .values(
                id=1,
                college_id=1,
                user_id=1,
                actions=["academic.read"],
                status="ACTIVE",
                granted_by=1,
                lock_version=1,
                **stamp,
            )
        )
        db.commit()
        migration = runpy.run_path(
            str(
                Path(__file__).parents[2]
                / "migrations/versions/f26a1014e001_enrollment_lifecycle.py"
            )
        )
        context = MigrationContext.configure(db)
        with Operations.context(context):
            migration["upgrade"]()
        assert compare_metadata(context, Base.metadata) == []
        assert db.execute(
            sa.text("SELECT student_no, administrative_class_id FROM student")
        ).one() == ("0001", 1)
        assert db.execute(
            sa.text("SELECT college_id,historical_confirmed,revision FROM student_enrollment")
        ).one() == (1, 0, 0)
        assert db.scalar(sa.text("SELECT college_id FROM teacher_college_binding")) == 1
        assert db.scalar(sa.text("SELECT COUNT(*) FROM user_permission")) == 0
        assert (
            db.scalar(
                sa.text("SELECT COUNT(*) FROM permission WHERE code='administrator_account.manage'")
            )
            == 1
        )
        with Operations.context(context):
            migration["downgrade"]()
        assert db.scalar(sa.text("SELECT COUNT(*) FROM student")) == 1
    engine.dispose()
