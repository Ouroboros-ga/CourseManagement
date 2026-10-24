"""Persist private interactive conversations and fenced send attempts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1025a010"
down_revision = "f26a1024a009"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    def fk(table, column, target):
        return sa.ForeignKey(
            f"{target}.id", ondelete="RESTRICT", name=f"fk_{table}_{column}_{target}"
        )

    options = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_0900_ai_ci",
    }
    op.create_table(
        "agent_conversation",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "actor_user_id",
            sa.BigInteger(),
            fk("agent_conversation", "actor_user_id", "user_account"),
            nullable=False,
        ),
        sa.Column(
            "source_session_id",
            sa.BigInteger(),
            fk("agent_conversation", "source_session_id", "auth_session"),
            nullable=False,
        ),
        sa.Column(
            "college_id",
            sa.BigInteger(),
            fk("agent_conversation", "college_id", "college"),
            nullable=False,
        ),
        sa.Column(
            "semester_id",
            sa.BigInteger(),
            fk("agent_conversation", "semester_id", "semester"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("app_key_id", sa.String(64), nullable=False),
        sa.Column("remote_conversation_id", sa.String(32), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("remote_conversation_id", name="uq_agent_conversation_remote"),
        sa.CheckConstraint(
            "state IN ('OPEN','UNCERTAIN','CLOSED')", name=op.f("ck_agent_conversation_state")
        ),
        **options,
    )
    op.create_index(
        "ix_agent_conversation_owner",
        "agent_conversation",
        ["actor_user_id", "source_session_id", "created_at"],
    )
    op.create_table(
        "agent_turn",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            fk("agent_turn", "conversation_id", "agent_conversation"),
            nullable=False,
        ),
        sa.Column(
            "run_id", sa.BigInteger(), fk("agent_turn", "run_id", "agent_run"), nullable=False
        ),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("remote_request_id", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempt_token", sa.String(64)),
        sa.Column("deadline_at", timestamp, nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("conversation_id", "request_key", name="uq_agent_turn_request"),
        sa.UniqueConstraint("run_id", name="uq_agent_turn_run"),
        sa.UniqueConstraint("remote_request_id", name="uq_agent_turn_remote_request"),
        sa.CheckConstraint(
            "state IN ('SENDING','SUCCEEDED','FAILED','UNCERTAIN')",
            name=op.f("ck_agent_turn_state"),
        ),
        **options,
    )
    op.create_index("ix_agent_turn_conversation", "agent_turn", ["conversation_id", "id"])


def downgrade():
    # All guards precede any DROP: MySQL DDL is not transactionally reversible.
    for name in ("agent_conversation", "agent_turn"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first():
            raise RuntimeError(f"{name} contains conversation history; retain both tables")
    op.drop_index("ix_agent_turn_conversation", table_name="agent_turn")
    op.drop_table("agent_turn")
    op.drop_index("ix_agent_conversation_owner", table_name="agent_conversation")
    op.drop_table("agent_conversation")
