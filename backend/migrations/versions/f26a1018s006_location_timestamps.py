"""Add timestamp metadata omitted from the occurrence override migration.

Existing overrides retain their location and revision. Their metadata timestamps
start at this schema repair; actual location-change times remain in the immutable
change chain. Keep s004 intact for databases that have already applied it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1018s006"
down_revision = "f26a1017s005"
branch_labels = None
depends_on = None


def upgrade():
    # MySQL requires the default precision to match DATETIME(3).
    now = "CURRENT_TIMESTAMP(3)" if op.get_bind().dialect.name == "mysql" else "CURRENT_TIMESTAMP"
    with op.batch_alter_table("occurrence_location_override") as batch:
        for name in ("created_at", "updated_at"):
            batch.add_column(sa.Column(
                name, sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
                nullable=False, server_default=sa.text(now),
            ))
    # Defaults only populate pre-existing rows; application UTC timestamps remain authoritative.
    with op.batch_alter_table("occurrence_location_override") as batch:
        for name in ("created_at", "updated_at"):
            batch.alter_column(name, server_default=None)


def downgrade():
    with op.batch_alter_table("occurrence_location_override") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
