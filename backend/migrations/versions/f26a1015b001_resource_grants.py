"""Explicit resource ceilings; NULL preserves already issued whole-college grants."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015b001"
down_revision = "f26a1015a001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scoped_grant", sa.Column("resource_scope", sa.JSON(), nullable=True))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Grant downgrade requires a live resource-scope preflight")
    table = sa.table("scoped_grant", sa.column("resource_scope", sa.JSON()))
    if any(value and value.get("kind") != "COLLEGE"
           for value in op.get_bind().scalars(sa.select(table.c.resource_scope))):
        raise RuntimeError("Limited grants exist; dropping scope would widen permissions")
    with op.batch_alter_table("scoped_grant") as batch:
        batch.drop_column("resource_scope")
