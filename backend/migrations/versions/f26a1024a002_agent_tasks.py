"""Add persistent agent tasks and leased read-tool jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1024a002"
down_revision = "f26a1024a001"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    options = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4",
                   mysql_collate="utf8mb4_0900_ai_ci")
    op.create_table(
        "agent_task",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("agent_run.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(),
                  sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_session_id", sa.BigInteger(),
                  sa.ForeignKey("auth_session.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("actor_user_id", "source_session_id", "request_key",
                            name="uq_agent_task_request"), **options,
    )
    op.create_index("ix_agent_task_actor_created", "agent_task", ["actor_user_id", "created_at"])
    op.create_index("ix_agent_task_run_status", "agent_task", ["run_id", "status"])
    op.create_table(
        "agent_job",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("agent_task.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", timestamp, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("attempt_token", sa.String(64)),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_until", timestamp),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("task_id", "stage", name="uq_agent_job_task_stage"), **options,
    )
    op.create_index("ix_agent_job_dispatch", "agent_job", ["status", "available_at", "id"])


def downgrade():
    for table in ("agent_job", "agent_task"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{table} contains task records; retain tables during rollback")
    op.drop_table("agent_job")
    op.drop_table("agent_task")
