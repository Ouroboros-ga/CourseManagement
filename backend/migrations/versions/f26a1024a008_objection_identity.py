"""Bind precheck runs to a job and an execution-attempt digest."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1024a008"
down_revision = "f26a1024a007"
branch_labels = None
depends_on = None

OLD_SOURCE_CHECK = (
    "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
    "AND workflow_kind IS NOT NULL AND workflow_kind = 'change' "
    "AND auto_change_execution_id IS NOT NULL) OR "
    "(entry_kind IN ('MANAGEMENT', 'SELF_SERVICE') AND source_session_id IS NOT NULL "
    "AND workflow_kind IS NULL AND auto_change_execution_id IS NULL)"
)
SOURCE_CHECK = (
    "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
    "AND workflow_kind IS NOT NULL AND workflow_kind = 'change' "
    "AND auto_change_execution_id IS NOT NULL AND objection_precheck_job_id IS NULL "
    "AND objection_precheck_attempt_digest IS NULL) OR "
    "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
    "AND workflow_kind IS NOT NULL AND workflow_kind = 'objection' "
    "AND auto_change_execution_id IS NULL AND objection_precheck_job_id IS NOT NULL "
    "AND objection_precheck_attempt_digest IS NOT NULL) OR "
    "(entry_kind IN ('MANAGEMENT', 'SELF_SERVICE') AND source_session_id IS NOT NULL "
    "AND workflow_kind IS NULL AND auto_change_execution_id IS NULL "
    "AND objection_precheck_job_id IS NULL AND objection_precheck_attempt_digest IS NULL)"
)


def upgrade():
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_constraint(op.f("ck_agent_run_identity_source"), type_="check")
        batch.add_column(sa.Column("objection_precheck_job_id", sa.BigInteger()))
        batch.add_column(sa.Column("objection_precheck_attempt_digest", sa.String(64)))
        batch.create_foreign_key(
            "fk_agent_run_objection_job",
            "objection_precheck_job",
            ["objection_precheck_job_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint("uq_agent_run_objection_job", ["objection_precheck_job_id"])
        batch.create_check_constraint(op.f("ck_agent_run_identity_source"), SOURCE_CHECK)


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM agent_run WHERE workflow_kind = 'objection' "
                "OR objection_precheck_job_id IS NOT NULL "
                "OR objection_precheck_attempt_digest IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("agent_run contains precheck provenance; retain identity columns")
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_constraint(op.f("ck_agent_run_identity_source"), type_="check")
        batch.drop_constraint("fk_agent_run_objection_job", type_="foreignkey")
        batch.drop_constraint("uq_agent_run_objection_job", type_="unique")
        batch.drop_column("objection_precheck_attempt_digest")
        batch.drop_column("objection_precheck_job_id")
        batch.create_check_constraint(op.f("ck_agent_run_identity_source"), OLD_SOURCE_CHECK)
