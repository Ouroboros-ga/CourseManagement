"""Keep revoked assignment history while retaining one active assignee per task.

Revision ID: c9b4a73e5d21
Revises: 6f4c2a91d8e0
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "c9b4a73e5d21"
down_revision: str | None = "6f4c2a91d8e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # MySQL 不允许持久生成列的基列参与级联删除；受派历史本来也不应随任务物理删除。
    op.drop_constraint("fk_inspection_assignment_task_id_inspection_task",
                       "inspection_assignment", type_="foreignkey")
    op.create_foreign_key("fk_inspection_assignment_task_id_inspection_task",
                          "inspection_assignment", "inspection_task", ["task_id"], ["id"],
                          ondelete="RESTRICT")
    op.add_column(
        "inspection_assignment",
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")),
    )
    op.add_column(
        "inspection_assignment",
        sa.Column(
            "active_task_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Computed(
                "CASE WHEN revoked_at IS NULL THEN task_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    # MySQL UNIQUE permits multiple NULL values, so any number of historical
    # rows can share task_id while exactly one unrevoked row may remain.
    op.create_unique_constraint(
        op.f("uq_inspection_assignment_active_task_id"),
        "inspection_assignment",
        ["active_task_id"],
    )
    op.create_index(
        op.f("ix_inspection_assignment_task_id"),
        "inspection_assignment",
        ["task_id"],
    )
    # The original unique index name is explicit in revision 949e8719895b.
    op.drop_constraint(
        op.f("uq_inspection_assignment_task_id"),
        "inspection_assignment",
        type_="unique",
    )


def downgrade() -> None:
    bind = op.get_bind()
    revoked = bind.execute(sa.text(
        "SELECT id FROM inspection_assignment WHERE revoked_at IS NOT NULL LIMIT 1"
    )).first()
    if revoked is not None:
        raise RuntimeError(
            "无法降级：已有失效受派历史；移除 revoked_at 会把历史误认为当前受派"
        )
    duplicate = bind.execute(sa.text(
        "SELECT task_id FROM inspection_assignment "
        "GROUP BY task_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate is not None:
        raise RuntimeError(
            "无法降级：同一任务已有多条受派；旧 task_id 唯一约束不能保留这些记录"
        )
    op.create_unique_constraint(
        op.f("uq_inspection_assignment_task_id"),
        "inspection_assignment",
        ["task_id"],
    )
    op.drop_index(op.f("ix_inspection_assignment_task_id"), table_name="inspection_assignment")
    op.drop_constraint(
        op.f("uq_inspection_assignment_active_task_id"),
        "inspection_assignment",
        type_="unique",
    )
    op.drop_column("inspection_assignment", "active_task_id")
    op.drop_column("inspection_assignment", "revoked_at")
    op.drop_constraint("fk_inspection_assignment_task_id_inspection_task",
                       "inspection_assignment", type_="foreignkey")
    op.create_foreign_key("fk_inspection_assignment_task_id_inspection_task",
                          "inspection_assignment", "inspection_task", ["task_id"], ["id"],
                          ondelete="CASCADE")
