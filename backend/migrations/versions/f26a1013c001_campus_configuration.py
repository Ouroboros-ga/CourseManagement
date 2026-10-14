"""Add campus configuration without guessing legacy business ownership.

Revision ID: f26a1013c001
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "f26a1013c001"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4",
           "mysql_collate": "utf8mb4_0900_ai_ci"}
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
NAME_KEY = sa.String(128, collation="utf8mb4_bin").with_variant(sa.String(128), "sqlite")


def timestamps():
    return [sa.Column("created_at", DT, nullable=False),
            sa.Column("updated_at", DT, nullable=False)]


def primary():
    return sa.Column("id", ID, primary_key=True, autoincrement=True)


def college_ref():
    return sa.Column("college_id", ID, sa.ForeignKey("college.id", ondelete="RESTRICT"),
                     nullable=False)


def version():
    return sa.Column("lock_version", sa.Integer(), nullable=False)


def upgrade():
    op.create_table("school", primary(), sa.Column("code", sa.String(32), nullable=False),
                    sa.Column("name", sa.String(128), nullable=False),
                    sa.Column("singleton_key", sa.Integer(), nullable=False), version(), *timestamps(),
                    sa.UniqueConstraint("code", name="uq_school_code"),
                    sa.UniqueConstraint("singleton_key", name="uq_school_singleton_key"),
                    sa.CheckConstraint("singleton_key = 1", name="school_singleton"), **OPTIONS)
    op.create_table("college", primary(),
                    sa.Column("school_id", ID, sa.ForeignKey("school.id", ondelete="RESTRICT"),
                              nullable=False),
                    sa.Column("code", sa.String(32), nullable=False),
                    sa.Column("name", sa.String(128), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False), version(),
                    sa.Column("authorization_revision", sa.Integer(), nullable=False),
                    sa.Column("configuration_revision", sa.Integer(), nullable=False),
                    *timestamps(), sa.UniqueConstraint("school_id", "code",
                                                       name="uq_college_school_code"),
                    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="college_status"),
                    **OPTIONS)
    op.create_table("scoped_grant", primary(), college_ref(),
                    sa.Column("user_id", ID, sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
                              nullable=False),
                    sa.Column("actions", sa.JSON(), nullable=False),
                    sa.Column("starts_at", DT), sa.Column("expires_at", DT),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("granted_by", ID,
                              sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False),
                    version(), *timestamps(),
                    sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="scoped_grant_status"),
                    **OPTIONS)
    op.create_index("ix_scoped_grant_college_id", "scoped_grant", ["college_id"])
    op.create_index("ix_scoped_grant_user_id", "scoped_grant", ["user_id"])
    op.create_table("course_type", primary(), college_ref(),
                    sa.Column("code", sa.String(32), nullable=False),
                    sa.Column("name", sa.String(128), nullable=False),
                    sa.Column("normalized_name", NAME_KEY, nullable=False),
                    sa.Column("description", sa.String(512), nullable=False),
                    sa.Column("display_color", sa.String(7), nullable=False),
                    sa.Column("sort_order", sa.Integer(), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False), version(), *timestamps(),
                    sa.UniqueConstraint("college_id", "id", name="uq_course_type_college_id"),
                    sa.UniqueConstraint("college_id", "code", name="uq_course_type_college_code"),
                    sa.UniqueConstraint("college_id", "normalized_name",
                                        name="uq_course_type_college_name"),
                    sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="course_type_status"),
                    **OPTIONS)
    op.create_table("volunteer_group", primary(), college_ref(),
                    sa.Column("name", sa.String(128), nullable=False),
                    sa.Column("normalized_name", NAME_KEY, nullable=False),
                    sa.Column("owner_user_id", ID,
                              sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("starts_on", sa.Date()), sa.Column("ends_on", sa.Date()),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("config_version", sa.Integer(), nullable=False), version(),
                    *timestamps(),
                    sa.UniqueConstraint("college_id", "id", name="uq_volunteer_group_college_id"),
                    sa.UniqueConstraint("college_id", "normalized_name",
                                        name="uq_volunteer_group_name"),
                    sa.CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')",
                                       name="volunteer_group_status"), **OPTIONS)
    op.create_table("group_config_version", primary(), college_ref(),
                    sa.Column("group_id", ID, nullable=False),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("configuration", sa.JSON(), nullable=False),
                    sa.Column("published_by", ID,
                              sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False),
                    *timestamps(),
                    sa.ForeignKeyConstraint(["college_id", "group_id"],
                                            ["volunteer_group.college_id", "volunteer_group.id"],
                                            ondelete="RESTRICT"),
                    sa.UniqueConstraint("group_id", "version", name="uq_group_config_version"),
                    sa.UniqueConstraint("college_id", "id", name="uq_group_config_college_id"),
                    **OPTIONS)
    op.create_table("group_scope_type",
                    sa.Column("config_id", ID, primary_key=True),
                    sa.Column("course_type_id", ID, primary_key=True), college_ref(),
                    sa.Column("is_inspection_scope", sa.Boolean(), nullable=False),
                    sa.ForeignKeyConstraint(["college_id", "config_id"],
                                            ["group_config_version.college_id", "group_config_version.id"],
                                            ondelete="RESTRICT"),
                    sa.ForeignKeyConstraint(["college_id", "course_type_id"],
                                            ["course_type.college_id", "course_type.id"],
                                            ondelete="RESTRICT"), **OPTIONS)


def downgrade():
    for table in ("group_scope_type", "group_config_version", "volunteer_group", "course_type",
                  "scoped_grant", "college", "school"):
        op.drop_table(table)
