"""Keep the temporary WeChat binding number when an official number arrives."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1019s007"
down_revision = "f26a1019d001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("faculty_staff") as batch:
        batch.add_column(sa.Column("temporary_staff_no", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_staff_school_temporary_number", ["school_id", "temporary_staff_no"])


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM faculty_staff WHERE temporary_staff_no IS NOT NULL"
    )):
        raise RuntimeError("Temporary numbers exist; keep the additive schema during rollback")
    with op.batch_alter_table("faculty_staff") as batch:
        batch.drop_constraint("uq_staff_school_temporary_number", type_="unique")
        batch.drop_column("temporary_staff_no")
