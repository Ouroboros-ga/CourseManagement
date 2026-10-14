"""Immutable official timetable publication and audience, no private timetable.

Revision ID: f26a1014p001
Revises: f26a1014e001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1014p001"
down_revision = "f26a1014e001"
branch_labels = None
depends_on = None

OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


def upgrade():
    op.create_table(
        "academic_publication",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id", ID, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id", ID, sa.ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column(
            "published_by",
            ID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", DT, nullable=False),
        sa.UniqueConstraint(
            "college_id", "semester_id", "version", name="uq_academic_publication_version"
        ),
        **OPTIONS,
    )
    op.create_table(
        "published_schedule",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column(
            "publication_id",
            ID,
            sa.ForeignKey("academic_publication.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_schedule_id", sa.String(20), nullable=False),
        sa.Column("segment_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "publication_id",
            "source_schedule_id",
            "segment_no",
            name="uq_published_schedule_source",
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_published_schedule_publication_id", "published_schedule", ["publication_id"]
    )
    op.create_table(
        "published_schedule_student",
        sa.Column("occurrence_dates", sa.JSON(), nullable=False),
        sa.Column(
            "published_schedule_id",
            ID,
            sa.ForeignKey("published_schedule.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "student_id", ID, sa.ForeignKey("student.id", ondelete="RESTRICT"), primary_key=True
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_published_schedule_student_student_id", "published_schedule_student", ["student_id"]
    )
    op.create_table(
        "publication_audience",
        sa.Column(
            "publication_id",
            ID,
            sa.ForeignKey("academic_publication.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "student_id", ID, sa.ForeignKey("student.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        **OPTIONS,
    )
    op.create_index("ix_publication_audience_student_id", "publication_audience", ["student_id"])
    op.create_table(
        "personal_timetable",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column(
            "student_id", ID, sa.ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id", ID, sa.ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint(
            "student_id", "semester_id", name="uq_personal_timetable_student_semester"
        ),
        **OPTIONS,
    )


def downgrade():
    op.drop_table("personal_timetable")
    op.drop_table("publication_audience")
    op.drop_table("published_schedule_student")
    op.drop_table("published_schedule")
    op.drop_table("academic_publication")
