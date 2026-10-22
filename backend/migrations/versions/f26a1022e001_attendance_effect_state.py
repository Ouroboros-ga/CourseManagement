"""Add the attendance conclusion validity axis (DEC-01 withdrawal).

志愿者本人撤回提交后，据以生成的考勤退出有效结论但行必须保留：attendance_record_version
是不可变历史，objection.attendance_record_id 是 ON DELETE CASCADE 外键，删行会连带销毁版本
与异议。因此用第二条轴表达"是否仍然有效"，而不是改写 effective_type 或删除记录。

默认过滤由 app/modules/attendance/effect_scope.py 的 Session 监听器提供，业务读取看不到
WITHDRAWN 行；历史可达、证据鉴权与级联清理路径显式放行。

source_type 的检查约束同时放宽，加入 WITHDRAWAL 以记录撤回这一事实本身。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f26a1022e001"
down_revision: str | None = "f26a1021w001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EFFECT_STATES = "('EFFECTIVE','WITHDRAWN')"
_NEW_SOURCE_TYPES = "('SUBMISSION','CORRECTION','OBJECTION_FINAL','WITHDRAWAL')"
_OLD_SOURCE_TYPES = "('SUBMISSION','CORRECTION','OBJECTION_FINAL')"


def upgrade() -> None:
    with op.batch_alter_table("attendance_record") as batch:
        batch.add_column(
            sa.Column(
                "effect_state",
                sa.String(16),
                nullable=False,
                server_default="EFFECTIVE",
            )
        )
        batch.create_check_constraint(
            "ck_attendance_record_effect_state", f"effect_state IN {_EFFECT_STATES}"
        )
    op.create_index(
        "ix_attendance_record_effect_state", "attendance_record", ["effect_state"]
    )

    with op.batch_alter_table("attendance_record_version") as batch:
        try:
            batch.drop_constraint("ck_attendance_record_version_source_type", type_="check")
        except Exception:
            pass
        batch.create_check_constraint(
            "ck_attendance_record_version_source_type", f"source_type IN {_NEW_SOURCE_TYPES}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    withdrawn = bind.scalar(
        sa.text("SELECT COUNT(*) FROM attendance_record WHERE effect_state <> 'EFFECTIVE'")
    )
    if withdrawn:
        raise RuntimeError(
            f"{withdrawn} 条考勤已撤回，回滚会把它们重新算成有效结论；请保留附加列。"
        )
    op.drop_index("ix_attendance_record_effect_state", table_name="attendance_record")
    with op.batch_alter_table("attendance_record") as batch:
        batch.drop_constraint("ck_attendance_record_effect_state", type_="check")
        batch.drop_column("effect_state")

    if bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM attendance_record_version WHERE source_type = 'WITHDRAWAL'"
        )
    ):
        raise RuntimeError(
            "已存在撤回版本记录，回滚检查约束会留下无法解释的来源类型；请保留放宽后的约束。"
        )
    with op.batch_alter_table("attendance_record_version") as batch:
        try:
            batch.drop_constraint("ck_attendance_record_version_source_type", type_="check")
        except Exception:
            pass
        batch.create_check_constraint(
            "ck_attendance_record_version_source_type", f"source_type IN {_OLD_SOURCE_TYPES}"
        )
