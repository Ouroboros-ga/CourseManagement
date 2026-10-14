"""College time publication and explicit task time snapshots.

Revision ID: f26a1014t001
Revises: f26a1014p001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1014t001"
down_revision = "f26a1014p001"
branch_labels = None
depends_on = None
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


def upgrade():
    op.create_table(
        "college_time_version",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id", ID, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id", ID, sa.ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column(
            "published_by",
            ID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # TimestampMixin writes UTC values explicitly; avoid a server-local fallback.
        sa.Column("created_at", DT, nullable=False),
        sa.Column("updated_at", DT, nullable=False),
        sa.UniqueConstraint("college_id", "semester_id", "version", name="uq_college_time_version"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_college_time_version_college_id", "college_time_version", ["college_id"])
    op.create_index("ix_college_time_version_semester_id", "college_time_version", ["semester_id"])
    op.add_column("inspection_task", sa.Column("activity_start_at", DT))
    op.add_column("inspection_task", sa.Column("activity_end_at", DT))
    op.add_column("inspection_task", sa.Column("time_snapshot", sa.JSON()))


def downgrade():
    op.drop_column("inspection_task", "time_snapshot")
    op.drop_column("inspection_task", "activity_end_at")
    op.drop_column("inspection_task", "activity_start_at")
    op.drop_table("college_time_version")
