"""Retain historical resources while removing them from daily management."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1019d001"
down_revision = "f26a1018s006"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("course_type", "volunteer_group", "inspection_task"):
        op.add_column(
            name,
            sa.Column(
                "deleted_at",
                sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
                nullable=True,
            ),
        )


def downgrade():
    # Refuse to erase deletion semantics. Restore retained resources explicitly first.
    bind = op.get_bind()
    for name in ("course_type", "volunteer_group", "inspection_task"):
        if bind.scalar(sa.text(f"SELECT COUNT(*) FROM {name} WHERE deleted_at IS NOT NULL")):
            raise RuntimeError("Restore retained resources before dropping deletion metadata")
    for name in ("inspection_task", "volunteer_group", "course_type"):
        op.drop_column(name, "deleted_at")
