"""Global approved volunteer busy intervals, without changing existing assignments."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015e001"
down_revision = "f26a1015d002"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "volunteer_unavailability",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "group_id",
            identity,
            sa.ForeignKey("volunteer_group.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id", identity, sa.ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column(
            "requested_by",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "decided_by",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_volunteer_unavailability_times"),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELED')",
            name="ck_volunteer_unavailability_status",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_volunteer_unavailability_student_status_start",
        "volunteer_unavailability",
        ["student_id", "status", "starts_at"],
    )
    op.create_index(
        "ix_volunteer_unavailability_group_semester",
        "volunteer_unavailability",
        ["group_id", "semester_id"],
    )


def downgrade():
    if op.get_context().as_sql or op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM volunteer_unavailability")
    ):
        raise RuntimeError("Unavailability facts exist; retain schema or restore a verified backup")
    op.drop_table("volunteer_unavailability")
