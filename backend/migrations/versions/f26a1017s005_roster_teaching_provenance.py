"""Roster provenance: which teaching class each frozen roster member belonged to.

合班任务里一条考勤记录只有 (task_id, student_id)，而教师更正与责任区审核都要逐学生判定
授课归属。名单快照此前只冻结行政班，没有冻结“该生属于本任务的哪个教学班”，于是只能拿
当前选课名单猜历史：学生转班后，原本的 B 班记录会被 A 班教师读到并可改写。

本迁移新增 ``task_roster_member_class``，由名单生成时按当时的课班参与关系写入。历史版本
保持无记录：读取仍然可见，但本人写入口按“授课归属待核对”限制，不做批量回填，也不按姓名、
课程名或教室猜测归属。

Revision ID: f26a1017s005
Revises: f26a1017s004
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "f26a1017s005"
down_revision = "f26a1017s004"
branch_labels = None
depends_on = None

OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")


def upgrade():
    op.create_table(
        "task_roster_member_class",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "task_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("inspection_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("roster_version", sa.Integer(), nullable=False),
        sa.Column(
            "student_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("student.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "teaching_class_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("teaching_class.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_id",
            "roster_version",
            "student_id",
            "teaching_class_id",
            name="uq_task_roster_member_class",
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_roster_member_class_task", "task_roster_member_class", ["task_id", "roster_version"]
    )
    op.create_index(
        "ix_roster_member_class_student", "task_roster_member_class", ["task_id", "roster_version", "student_id"]
    )
    op.create_index(
        "ix_roster_member_class_class", "task_roster_member_class", ["teaching_class_id"]
    )


def downgrade():
    # 归属来源是更正授权的依据；回退前先确认没有依赖它的本人更正记录。
    op.drop_index("ix_roster_member_class_class", table_name="task_roster_member_class")
    op.drop_index("ix_roster_member_class_student", table_name="task_roster_member_class")
    op.drop_index("ix_roster_member_class_task", table_name="task_roster_member_class")
    op.drop_table("task_roster_member_class")
