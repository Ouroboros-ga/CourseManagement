"""Add independent personal display backups without rewriting legacy entries."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1016b001"
down_revision = "f26a1016a003"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    op.create_table(
        "personal_timetable_backup",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "student_id", identity, sa.ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("schedule_data", sa.JSON(), nullable=False),
        sa.Column("backup_version", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "student_id", "semester_id", name="uq_timetable_backup_student_semester"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade():
    op.drop_table("personal_timetable_backup")
