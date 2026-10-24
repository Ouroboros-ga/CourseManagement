"""Bind background runs to one policy execution without a synthetic login session."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1024a004"
down_revision = "f26a1024a003"
branch_labels = None
depends_on = None

SOURCE_CHECK = (
    "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
    "AND workflow_kind IS NOT NULL AND workflow_kind = 'change' "
    "AND auto_change_execution_id IS NOT NULL) OR "
    "(entry_kind IN ('MANAGEMENT', 'SELF_SERVICE') AND source_session_id IS NOT NULL "
    "AND workflow_kind IS NULL AND auto_change_execution_id IS NULL)"
)


def upgrade():
    with op.batch_alter_table("agent_run") as batch:
        batch.alter_column("source_session_id", existing_type=sa.BigInteger(), nullable=True)
        batch.add_column(sa.Column("workflow_kind", sa.String(24)))
        batch.add_column(sa.Column("auto_change_execution_id", sa.BigInteger()))
        batch.create_foreign_key(
            "fk_agent_run_change_execution",
            "auto_change_execution",
            ["auto_change_execution_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_agent_run_change_execution", ["auto_change_execution_id"]
        )
        batch.create_check_constraint(op.f("ck_agent_run_identity_source"), SOURCE_CHECK)


def downgrade():
    # Do not strip policy provenance or invent session IDs to satisfy the old schema.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM agent_run WHERE entry_kind = 'AUTOMATION' "
                "OR source_session_id IS NULL "
                "OR workflow_kind IS NOT NULL OR auto_change_execution_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("agent_run contains automation history; retain identity columns")
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_constraint(op.f("ck_agent_run_identity_source"), type_="check")
        batch.drop_constraint("fk_agent_run_change_execution", type_="foreignkey")
        batch.drop_constraint("uq_agent_run_change_execution", type_="unique")
        batch.drop_column("auto_change_execution_id")
        batch.drop_column("workflow_kind")
        batch.alter_column("source_session_id", existing_type=sa.BigInteger(), nullable=False)
