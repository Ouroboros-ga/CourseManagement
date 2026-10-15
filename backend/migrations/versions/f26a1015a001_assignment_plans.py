"""Persist actor-bound warning confirmations and idempotent assignment results."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015a001"
down_revision = "f26a1015u001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "assignment_confirmation_plan",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "actor_user_id",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('READY','COMMITTED')", name="ck_assignment_plan_status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Plan downgrade requires a live audit preflight")
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM assignment_confirmation_plan")):
        raise RuntimeError(
            "Assignment plan audit facts exist; retain schema or restore verified backup"
        )
    op.drop_table("assignment_confirmation_plan")
