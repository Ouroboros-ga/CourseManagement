"""Independent objection AI advice and college policy; no formal attendance writes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1024a007"
down_revision = "f26a1024a006"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    options = dict(
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci"
    )
    op.create_table(
        "objection_precheck_policy",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "college_id",
            sa.BigInteger(),
            sa.ForeignKey("college.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "authorizer_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("college_id"),
        **options,
    )
    op.create_table(
        "objection_precheck_job",
        sa.Column("id", pk, primary_key=True, autoincrement=True),
        sa.Column(
            "objection_id",
            sa.BigInteger(),
            sa.ForeignKey("objection.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("college_id", sa.BigInteger(), sa.ForeignKey("college.id", ondelete="RESTRICT")),
        sa.Column(
            "policy_id",
            sa.BigInteger(),
            sa.ForeignKey("objection_precheck_policy.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "authorizer_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "initiated_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_token", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("result_json", sa.JSON()),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint(
            "objection_id",
            "source_digest",
            "policy_version",
            "environment",
            name="uq_objection_precheck_source",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_objection_precheck_status",
        ),
        **options,
    )
    op.create_index(
        "ix_objection_precheck_job_objection_id", "objection_precheck_job", ["objection_id"]
    )
    op.create_index("ix_objection_precheck_job_status", "objection_precheck_job", ["status"])


def downgrade():
    # Check both tables before any DDL: MySQL DDL cannot roll back an earlier drop.
    for table in ("objection_precheck_job", "objection_precheck_policy"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{table} contains precheck history; retain during rollback")
    op.drop_table("objection_precheck_job")
    op.drop_table("objection_precheck_policy")
