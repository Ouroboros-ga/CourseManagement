"""Keep original preview batches and workspace group receipts in one transaction."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1025a013"
down_revision = "f26a1025a012"
branch_labels = None
depends_on = None


def _state(states, size):
    with op.batch_alter_table("agent_import_workspace") as batch:
        batch.drop_constraint(op.f("ck_agent_import_workspace_state"), type_="check")
        batch.alter_column(
            "state",
            existing_type=sa.String(16 if size == 24 else 24),
            type_=sa.String(size),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            op.f("ck_agent_import_workspace_state"), f"state IN ({states})"
        )


def upgrade():
    op.add_column("agent_import_workspace", sa.Column("preview_json", sa.JSON()))
    _state(
        "'QUEUED','PROCESSING','READY','FAILED','CANCELED','PREVIEW_QUEUED','PREVIEW_PROCESSING'",
        24,
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM agent_import_workspace WHERE preview_json IS NOT NULL "
                "OR state IN ('PREVIEW_QUEUED','PREVIEW_PROCESSING') LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("agent_import_workspace contains preview receipts; retain preview_json")
    _state("'QUEUED','PROCESSING','READY','FAILED','CANCELED'", 16)
    op.drop_column("agent_import_workspace", "preview_json")
