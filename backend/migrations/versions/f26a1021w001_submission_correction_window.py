"""Add the volunteer self-correction lifecycle columns to submissions (DEC-01).

撤回与改版不改动 review_status：既有读取路径以 APPROVED 判断"已形成正式结论"，
把撤回伪装成 REJECTED 会让考勤、名单、归档与统计一起失真。有效性单独由
submission_state 表达，历史提交原样保留。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1021w001"
down_revision = "f26a1019s007"
branch_labels = None
depends_on = None

_STATES = "('ACTIVE','SUPERSEDED','WITHDRAWN')"


def upgrade():
    with op.batch_alter_table("inspection_submission") as batch:
        batch.add_column(
            sa.Column(
                "submission_state",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'ACTIVE'"),
            )
        )
        batch.add_column(
            sa.Column(
                "superseded_by_submission_id",
                sa.BigInteger(),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "withdrawn_at",
                sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("withdraw_reason", sa.String(512), nullable=True))
        batch.create_check_constraint(
            "ck_inspection_submission_state", f"submission_state IN {_STATES}"
        )
        batch.create_foreign_key(
            "fk_submission_superseded_by",
            "inspection_submission",
            ["superseded_by_submission_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_inspection_submission_submission_state",
        "inspection_submission",
        ["submission_state"],
    )


def downgrade():
    bind = op.get_bind()
    used = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM inspection_submission "
            "WHERE submission_state <> 'ACTIVE' OR superseded_by_submission_id IS NOT NULL"
        )
    )
    if used:
        raise RuntimeError(
            f"{used} 条提交已进入纠错生命周期，回滚会丢失有效性事实；请保留附加列。"
        )
    op.drop_index("ix_inspection_submission_submission_state", table_name="inspection_submission")
    with op.batch_alter_table("inspection_submission") as batch:
        batch.drop_constraint("fk_submission_superseded_by", type_="foreignkey")
        batch.drop_constraint("ck_inspection_submission_state", type_="check")
        batch.drop_column("withdraw_reason")
        batch.drop_column("withdrawn_at")
        batch.drop_column("superseded_by_submission_id")
        batch.drop_column("submission_state")
