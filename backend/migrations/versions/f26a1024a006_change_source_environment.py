"""Record source environment for new events; never infer legacy execution provenance."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1024a006"
down_revision = "f26a1024a005"
branch_labels = None
depends_on = None


def upgrade():
    # Old events remain NULL and are excluded from automatic dispatch/identity issuance.
    op.add_column("auto_change_execution", sa.Column("environment", sa.String(32), nullable=True))


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM auto_change_execution WHERE environment IS NOT NULL LIMIT 1")
        )
        .first()
    ):
        raise RuntimeError("execution provenance exists; retain source environment during rollback")
    with op.batch_alter_table("auto_change_execution") as batch:
        batch.drop_column("environment")
