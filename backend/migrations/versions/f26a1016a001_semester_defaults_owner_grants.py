"""Immutable school time defaults and separately revocable owner grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1016a001"
down_revision = "f26a1015h001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "school_semester_default",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "school_id", identity, sa.ForeignKey("school.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column(
            "period_template_version_id",
            identity,
            sa.ForeignKey("school_time_template_version.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "published_by",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.UniqueConstraint(
            "school_id", "semester_id", "version", name="uq_school_semester_default_version"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index(
        "ix_school_semester_default_semester_id", "school_semester_default", ["semester_id"]
    )
    op.add_column("college_time_version", sa.Column("source_template_id", identity, nullable=True))
    op.create_foreign_key(
        "fk_time_source_template",
        "college_time_version",
        "school_semester_default",
        ["source_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("scoped_grant", sa.Column("owner_group_id", identity, nullable=True))
    op.create_index("ix_scoped_grant_owner_group_id", "scoped_grant", ["owner_group_id"])
    op.create_foreign_key(
        "fk_grant_owner_group",
        "scoped_grant",
        "volunteer_group",
        ["owner_group_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint("fk_grant_owner_group", "scoped_grant", type_="foreignkey")
    op.drop_index("ix_scoped_grant_owner_group_id", table_name="scoped_grant")
    op.drop_column("scoped_grant", "owner_group_id")
    op.drop_constraint("fk_time_source_template", "college_time_version", type_="foreignkey")
    op.drop_column("college_time_version", "source_template_id")
    op.drop_table("school_semester_default")
