"""Retain append-only precheck retry attempts and their predecessor links."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1024a009"
down_revision = "f26a1024a008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("objection_precheck_job") as batch:
        batch.add_column(sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("retry_of_job_id", sa.BigInteger()))
        batch.drop_constraint("uq_objection_precheck_source", type_="unique")
        batch.create_unique_constraint(
            "uq_objection_precheck_source",
            [
                "objection_id",
                "source_digest",
                "policy_version",
                "environment",
                "attempt_no",
            ],
        )
        batch.create_foreign_key(
            "fk_precheck_retry_parent",
            "objection_precheck_job",
            ["retry_of_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_precheck_retry_parent", ["retry_of_job_id"])
        batch.create_check_constraint(op.f("ck_objection_precheck_attempt"), "attempt_no >= 1")


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM objection_precheck_job WHERE attempt_no <> 1 "
                "OR retry_of_job_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("precheck retry history exists; retain attempt provenance")
    with op.batch_alter_table("objection_precheck_job") as batch:
        batch.drop_constraint(op.f("ck_objection_precheck_attempt"), type_="check")
        batch.drop_constraint("fk_precheck_retry_parent", type_="foreignkey")
        batch.drop_constraint("uq_precheck_retry_parent", type_="unique")
        batch.drop_constraint("uq_objection_precheck_source", type_="unique")
        batch.create_unique_constraint(
            "uq_objection_precheck_source",
            [
                "objection_id",
                "source_digest",
                "policy_version",
                "environment",
            ],
        )
        batch.drop_column("retry_of_job_id")
        batch.drop_column("attempt_no")
