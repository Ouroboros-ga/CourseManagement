"""Align migration enrollment baseline effective_from with semester start date
to eliminate timetable roster cliff.
"""

import sqlalchemy as sa
from alembic import op

revision = "f26a1017a001"
down_revision = "f26a1016b001"
branch_labels = None
depends_on = None


def upgrade():
    # 将 2026-10-14 迁移脚本生成的初始存量学籍基线 effective_from 校准为学期首日 2026-09-14
    # 消除 2026-10-14 之前（第 1~4 周及第 5 周周一/周二）总课表与排班花名册的人数断崖
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE student_enrollment
            SET effective_from = '2026-09-14'
            WHERE revision = 0
              AND effective_from = '2026-10-14'
              AND superseded = 0
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE student_enrollment
            SET effective_from = '2026-10-14'
            WHERE revision = 0
              AND effective_from = '2026-09-14'
              AND superseded = 0
            """
        )
    )
