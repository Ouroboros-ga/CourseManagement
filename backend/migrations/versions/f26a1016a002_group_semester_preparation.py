"""Keep semester-specific organization rules separate from persistent identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1016a002"
down_revision = "f26a1016a001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "group_semester_preparation",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "group_id",
            identity,
            sa.ForeignKey("volunteer_group.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "config_id",
            identity,
            sa.ForeignKey("group_config_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.UniqueConstraint("group_id", "semester_id", name="uq_group_semester_preparation"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade():
    op.drop_table("group_semester_preparation")
