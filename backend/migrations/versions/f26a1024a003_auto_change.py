"""Policy-bound automatic reassignment and durable execution receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1024a003"
down_revision = "f26a1024a002"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    options = dict(
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci"
    )
    op.create_table(
        "auto_change_policy",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id",
            sa.BigInteger(),
            sa.ForeignKey("college.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            sa.ForeignKey("volunteer_group.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "semester_id",
            sa.BigInteger(),
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "authorizer_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_cutoff_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled_at", timestamp),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("college_id", "group_id", "semester_id", name="uq_auto_change_scope"),
        **options,
    )
    op.create_table(
        "auto_change_execution",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "policy_id",
            sa.BigInteger(),
            sa.ForeignKey("auto_change_policy.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            sa.BigInteger(),
            sa.ForeignKey("assignment_change_request.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "authorizer_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("assignment_confirmation_plan.id", ondelete="RESTRICT"),
        ),
        sa.Column("plan_revision", sa.String(64)),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("result_json", sa.JSON()),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        **options,
    )
    op.create_index("ix_auto_change_execution_status", "auto_change_execution", ["status"])


def downgrade():
    # Check every table before any DDL: MySQL DROP TABLE is not rolled back.
    for table in ("auto_change_execution", "auto_change_policy"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{table} contains policy history; retain tables during rollback")
    op.drop_table("auto_change_execution")
    op.drop_table("auto_change_policy")
