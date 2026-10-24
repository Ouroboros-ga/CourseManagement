"""Persist interactive agent identity associations, disabled by default."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "f26a1024a001"
down_revision = "f26a1022e001"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "agent_run",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column("app_key_id", sa.String(64), nullable=False),
        sa.Column("entry_kind", sa.String(24), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(),
                  sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_session_id", sa.BigInteger(),
                  sa.ForeignKey("auth_session.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("college_id", sa.BigInteger(), sa.ForeignKey("college.id", ondelete="RESTRICT")),
        sa.Column("semester_id", sa.BigInteger(), sa.ForeignKey("semester.id", ondelete="RESTRICT")),
        sa.Column("credential_digest", sa.String(64), nullable=False),
        sa.Column("credential_expires_at", timestamp, nullable=False),
        sa.Column("revoked_at", timestamp),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("credential_digest", name="uq_agent_run_credential_digest"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_agent_run_actor_created", "agent_run", ["actor_user_id", "created_at"])


def downgrade():
    # A code rollback can retain the compatible table; never erase runtime history implicitly.
    if op.get_bind().execute(sa.text("SELECT 1 FROM agent_run LIMIT 1")).first():
        raise RuntimeError("agent_run contains runtime records; retain the table during rollback")
    op.drop_index("ix_agent_run_actor_created", table_name="agent_run")
    op.drop_table("agent_run")
