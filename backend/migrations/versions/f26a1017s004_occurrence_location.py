"""Occurrence location override layer and append-only change chain.

地点覆盖按稳定课次键（``s:{shared_meeting_key 或 schedule.id}|{日期}``）单独持久化，
不改写正式课表的原始导入来源；教师换教室只影响该真实课次的任务目的地快照与地点
修订号，已完成任务的现场快照与历史报表保持不变。

Revision ID: f26a1017s004
Revises: f26a1017s003
Create Date: 2026-10-17

说明：任务规划中命名的 ``f26a1017s003_occurrence_location`` 已被教职工导入目标迁移
（T02 f26a1017s003_staff_import_targets）占用，因此本迁移顺延为 s004。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1017s004"
down_revision = "f26a1017s003"
branch_labels = None
depends_on = None

OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")


def upgrade():
    op.create_table(
        "occurrence_location_override",
        sa.Column(
            "occurrence_key",
            sa.String(128),
            primary_key=True,
        ),
        sa.Column(
            "school_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("school.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("location", sa.String(128), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("`revision` >= 0", name="occurrence_location_revision"),
        **OPTIONS,
    )
    op.create_index(
        "ix_occurrence_location_school",
        "occurrence_location_override",
        ["school_id", "occurrence_key"],
    )
    op.create_table(
        "occurrence_location_change",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("occurrence_key", sa.String(128), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("previous_location", sa.String(128), nullable=True),
        sa.Column("new_location", sa.String(128), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
            nullable=False,
        ),
        sa.Column("changed_by", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
            nullable=False,
        ),
        sa.CheckConstraint("revision_no >= 1", name="occurrence_location_change_revision"),
        **OPTIONS,
    )
    op.create_index("ix_occurrence_location_change_occurrence_key", "occurrence_location_change", ["occurrence_key"])


def downgrade():
    op.drop_table("occurrence_location_change")
    op.drop_table("occurrence_location_override")
