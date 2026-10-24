"""Queue existing conversation turns without duplicating task lifecycles."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1025a011"
down_revision = "f26a1025a010"
branch_labels = None
depends_on = None


def _state_constraint(states):
    with op.batch_alter_table("agent_turn") as batch:
        batch.drop_constraint(op.f("ck_agent_turn_state"), type_="check")
        batch.create_check_constraint(op.f("ck_agent_turn_state"), f"state IN ({states})")


def upgrade():
    _state_constraint("'QUEUED','SENDING','SUCCEEDED','FAILED','UNCERTAIN'")
    op.create_index("ix_agent_turn_queue", "agent_turn", ["state", "id"])
    op.create_index(
        "ix_agent_conversation_pool", "agent_conversation", ["environment", "app_key_id", "id"]
    )


def downgrade():
    # Refuse before any MySQL DDL: pending work cannot be represented on a010.
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM agent_turn WHERE state='QUEUED' LIMIT 1"))
        .first()
    ):
        raise RuntimeError("agent_turn contains QUEUED work; drain before downgrade")
    _state_constraint("'SENDING','SUCCEEDED','FAILED','UNCERTAIN'")
    op.drop_index("ix_agent_turn_queue", table_name="agent_turn")
    op.drop_index("ix_agent_conversation_pool", table_name="agent_conversation")
