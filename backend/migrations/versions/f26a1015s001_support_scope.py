"""Freeze the upper bound of cross-college support authorization."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015s001"
down_revision = "f26a1015d001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("volunteer_group_support", sa.Column("scope_snapshot", sa.JSON(), nullable=True))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Support downgrade requires a live authorization check")
    db = op.get_bind()
    table = sa.table("volunteer_group_support", sa.column("scope_snapshot", sa.JSON()))
    if db.scalar(
        sa.select(sa.func.count()).select_from(table).where(table.c.scope_snapshot.is_not(None))
    ):
        raise RuntimeError("Support authorizations exist; restore the verified pre-upgrade backup")
    op.drop_column("volunteer_group_support", "scope_snapshot")
