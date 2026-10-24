"""Weekly inspection policy and exact per-week execution receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1025a014"
down_revision = "f26a1025a013"
branch_labels = None
depends_on = None


def _reference(name, table, *, nullable=False, kind=None):
    return sa.Column(
        name,
        kind or sa.BigInteger(),
        sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade():
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    stamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    options = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }
    op.create_table(
        "weekly_inspection_plan",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column("environment", sa.String(32), nullable=False),
        _reference("college_id", "college"),
        _reference("group_id", "volunteer_group"),
        _reference("semester_id", "semester"),
        _reference("authorizer_user_id", "user_account"),
        _reference("group_config_id", "group_config_version"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", stamp, nullable=False),
        sa.Column("updated_at", stamp, nullable=False),
        sa.UniqueConstraint(
            "environment", "college_id", "group_id", "semester_id", name="uq_weekly_plan_scope"
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_weekly_inspection_plan_version")),
        **options,
    )
    op.create_index(
        "ix_weekly_plan_due", "weekly_inspection_plan", ["environment", "enabled", "id"]
    )
    op.create_table(
        "weekly_inspection_execution",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        _reference("plan_id", "weekly_inspection_plan"),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        _reference("authorizer_user_id", "user_account"),
        sa.Column("target_week", sa.Integer(), nullable=False),
        sa.Column("due_at", stamp, nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        _reference(
            "assignment_plan_id", "assignment_confirmation_plan", nullable=True, kind=sa.String(36)
        ),
        sa.Column("result_json", sa.JSON()),
        sa.Column("created_at", stamp, nullable=False),
        sa.Column("updated_at", stamp, nullable=False),
        sa.UniqueConstraint("plan_id", "target_week", name="uq_weekly_execution_week"),
        sa.CheckConstraint(
            "target_week >= 1 AND target_week <= 60",
            name=op.f("ck_weekly_inspection_execution_week"),
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','GENERATED','PREPARED','MISSED',"
            "'FAILED','NEEDS_REVIEW','CANCELED')",
            name=op.f("ck_weekly_inspection_execution_state"),
        ),
        **options,
    )
    op.create_index("ix_weekly_execution_state", "weekly_inspection_execution", ["status", "id"])


def downgrade():
    for name in ("weekly_inspection_execution", "weekly_inspection_plan"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first():
            raise RuntimeError(
                "weekly inspection contains policy or execution history; retain both tables"
            )
    op.drop_index("ix_weekly_execution_state", table_name="weekly_inspection_execution")
    op.drop_table("weekly_inspection_execution")
    op.drop_index("ix_weekly_plan_due", table_name="weekly_inspection_plan")
    op.drop_table("weekly_inspection_plan")
