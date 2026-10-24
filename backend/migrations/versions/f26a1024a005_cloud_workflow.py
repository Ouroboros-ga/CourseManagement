"""Durable cloud instance association and bounded dispatch/observation state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1024a005"
down_revision = "f26a1024a004"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    op.create_table(
        "agent_workflow_run",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_run.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("app_id", sa.String(32), nullable=False),
        sa.Column("domain", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24)),
        sa.Column("remote_run_id", sa.String(128)),
        sa.Column("remote_status", sa.String(24)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("attempt_token", sa.String(64), nullable=False),
        sa.Column("lease_until", timestamp),
        sa.Column("next_poll_at", timestamp),
        sa.Column("deadline_at", timestamp, nullable=False),
        sa.Column("create_attempts", sa.Integer(), nullable=False),
        sa.Column("poll_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("app_id", "domain", "remote_run_id", name="uq_agent_workflow_remote"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_agent_workflow_poll", "agent_workflow_run", ["state", "next_poll_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM agent_workflow_run LIMIT 1")).first():
        raise RuntimeError("agent_workflow_run contains tracking history; retain during rollback")
    op.drop_table("agent_workflow_run")
