"""Add immediate task execution exception without replacing attendance or deadline history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "f26a1023x001"
down_revision = "f26a1022e001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("inspection_task") as batch:
        batch.add_column(
            sa.Column(
                "exception_reported_at",
                sa.DateTime().with_variant(DATETIME(fsp=3), "mysql"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("exception_reported_by", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("exception_reporter_name", sa.String(128), nullable=True))
        batch.add_column(sa.Column("exception_reason", sa.String(512), nullable=True))
        batch.create_foreign_key(
            "fk_inspection_task_exception_reporter",
            "user_account",
            ["exception_reported_by"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("task_deadline_assessment") as batch:
        batch.drop_constraint("ck_task_deadline_assessment_result", type_="check")
        batch.create_check_constraint(
            "ck_task_deadline_assessment_result",
            "result IN ('VALID_SUBMISSION','OVERDUE_UNEXECUTED','CANCELED','EXCEPTION')",
        )


def downgrade():
    bind = op.get_bind()
    # Validate before MySQL's first implicitly committing DDL statement.
    if bind.scalar(
        sa.text("SELECT COUNT(*) FROM inspection_task WHERE exception_reported_at IS NOT NULL")
    ) or bind.scalar(
        sa.text("SELECT COUNT(*) FROM task_deadline_assessment WHERE result = 'EXCEPTION'")
    ):
        raise RuntimeError("已有异常事实，禁止删除其字段或约束；请保留附加结构")
    with op.batch_alter_table("task_deadline_assessment") as batch:
        batch.drop_constraint("ck_task_deadline_assessment_result", type_="check")
        batch.create_check_constraint(
            "ck_task_deadline_assessment_result",
            "result IN ('VALID_SUBMISSION','OVERDUE_UNEXECUTED','CANCELED')",
        )
    with op.batch_alter_table("inspection_task") as batch:
        batch.drop_constraint("fk_inspection_task_exception_reporter", type_="foreignkey")
        for name in (
            "exception_reason",
            "exception_reporter_name",
            "exception_reported_by",
            "exception_reported_at",
        ):
            batch.drop_column(name)
