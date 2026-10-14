"""Add nullable college ownership; no guessed data backfill or permission activation.

Revision ID: f26a1013c002
Revises: f26a1013c001
"""

from alembic import op
import sqlalchemy as sa

revision = "f26a1013c002"
down_revision = "f26a1013c001"
branch_labels = None
depends_on = None

TABLES = (
    "administrative_class",
    "teaching_class",
    "course_schedule",
    "inspection_task",
    "import_batch",
    "report",
)
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade():
    for table in TABLES:
        # batch supports the offline SQLite regression as well as MySQL ALTER.
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("college_id", ID, nullable=True))
            batch.add_column(
                sa.Column(
                    "ownership_version", sa.Integer(), nullable=False, server_default=sa.text("1")
                )
            )
            batch.create_index(f"ix_{table}_college_id", ["college_id"])
            batch.create_foreign_key(
                f"fk_{table}_college_id_college",
                "college",
                ["college_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade():
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_college_id_college", type_="foreignkey")
            batch.drop_index(f"ix_{table}_college_id")
            batch.drop_column("ownership_version")
            batch.drop_column("college_id")
