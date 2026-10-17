"""Add staff archives and explicit resource relationships, without inferred grants.

No backfill from teacher names. Once used, rollback via compatible application,
not by dropping relationship history with downgrade.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1017s001"
down_revision = "f26a1017c001"
branch_labels = None
depends_on = None

OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")


def _id():
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def _times():
    return [
        sa.Column(name, sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False)
        for name in ("created_at", "updated_at")
    ]


def _version():
    return sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1"))


def upgrade():
    op.create_table(
        "faculty_staff",
        _id(),
        sa.Column(
            "school_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("school.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "college_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("college.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("staff_no", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column(
            "user_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'ACTIVE'")),
        _version(),
        *_times(),
        sa.UniqueConstraint("school_id", "staff_no", name="uq_staff_school_number"),
        sa.UniqueConstraint("user_id", name="uq_faculty_staff_user_id"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="staff_status"),
        **OPTIONS,
    )
    op.create_index("ix_faculty_staff_college_id", "faculty_staff", ["college_id"])
    op.create_table(
        "teaching_staff_assignment",
        _id(),
        sa.Column(
            "staff_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("faculty_staff.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "semester_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("anchor_type", sa.String(16), nullable=False),
        sa.Column(
            "teaching_class_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("teaching_class.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "academic_offering_id",
            sa.String(32),
            sa.ForeignKey("academic_offering.id", ondelete="RESTRICT"),
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        _version(),
        *_times(),
        sa.CheckConstraint(
            "(anchor_type = 'LOCAL' AND teaching_class_id IS NOT NULL "
            "AND academic_offering_id IS NULL) OR "
            "(anchor_type = 'SHARED' AND teaching_class_id IS NULL "
            "AND academic_offering_id IS NOT NULL)",
            name="teaching_staff_anchor",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="teaching_staff_dates"
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_teaching_staff_assignment_teaching_class_id",
        "teaching_staff_assignment",
        ["teaching_class_id"],
    )
    op.create_index(
        "ix_teaching_staff_assignment_academic_offering_id",
        "teaching_staff_assignment",
        ["academic_offering_id"],
    )
    op.create_index(
        "ix_teaching_staff_current",
        "teaching_staff_assignment",
        ["staff_id", "semester_id", "effective_from", "effective_to"],
    )
    op.create_table(
        "class_staff_responsibility",
        _id(),
        sa.Column(
            "staff_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("faculty_staff.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "administrative_class_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("administrative_class.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("duty", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        _version(),
        *_times(),
        sa.CheckConstraint("duty IN ('HEAD_TEACHER','COUNSELOR')", name="staff_duty"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="class_staff_dates"
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_class_staff_current",
        "class_staff_responsibility",
        ["staff_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_class_staff_handover",
        "class_staff_responsibility",
        ["administrative_class_id", "duty", "effective_from"],
    )


def downgrade():
    op.drop_table("class_staff_responsibility")
    op.drop_table("teaching_staff_assignment")
    op.drop_table("faculty_staff")
