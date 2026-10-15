"""School templates and immutable source versions for copied college drafts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1015f001"
down_revision = "f26a1015e001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    options = dict(
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci"
    )
    op.create_table(
        "school_time_template",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "school_id", identity, sa.ForeignKey("school.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "normalized_name",
            sa.String(128, collation="utf8mb4_bin").with_variant(sa.String(128), "sqlite"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("school_id", "normalized_name", name="uq_school_time_template_name"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','INACTIVE')", name="ck_school_time_template_status"
        ),
        **options,
    )
    op.create_index("ix_school_time_template_school_id", "school_time_template", ["school_id"])
    op.create_table(
        "school_time_template_version",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            identity,
            sa.ForeignKey("school_time_template.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("periods", sa.JSON(), nullable=False),
        sa.Column(
            "published_by",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("template_id", "version", name="uq_school_time_template_version"),
        **options,
    )
    op.create_index(
        "ix_school_time_template_version_template_id",
        "school_time_template_version",
        ["template_id"],
    )
    with op.batch_alter_table("college_time_profile") as batch:
        batch.add_column(sa.Column("source_template_version_id", identity, nullable=True))
        batch.create_foreign_key(
            "fk_college_time_profile_source_template",
            "school_time_template_version",
            ["source_template_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_college_time_profile_source_template_version_id", ["source_template_version_id"]
        )


def downgrade():
    if op.get_context().as_sql or op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM school_time_template")
    ):
        raise RuntimeError("Template facts exist; retain schema or restore a verified backup")
    with op.batch_alter_table("college_time_profile") as batch:
        batch.drop_constraint("fk_college_time_profile_source_template", type_="foreignkey")
        batch.drop_index("ix_college_time_profile_source_template_version_id")
        batch.drop_column("source_template_version_id")
    op.drop_table("school_time_template_version")
    op.drop_table("school_time_template")
