"""Allow the three staff data kinds as real import_batch targets.

教职工档案、班级责任关系和授课关系此前借道 admin_roster/timetable 才能通过
ck_import_batch_target，导致批次列表、统计和授权口径都看到的是别名。这里把规范种类
写进约束；别名只作为历史行保留，不再由新批次产生。

Revision ID: f26a1017s003
Revises: f26a1017s002
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from contextlib import suppress

from alembic import op

revision = "f26a1017s003"
down_revision = "f26a1017s002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITH_STAFF = (
    "('roster','timetable','volunteer','admin_roster','grid_timetable','elective_course',"
    "'faculty_staff','class_responsibility','teaching_assignment')"
)
_WITHOUT_STAFF = (
    "('roster','timetable','volunteer','admin_roster','grid_timetable','elective_course')"
)


def upgrade() -> None:
    with op.batch_alter_table("import_batch") as batch_op:
        # 约束名随建表命名约定加前缀，历史环境不一定同名，删不掉时由重建覆盖。
        with suppress(Exception):
            batch_op.drop_constraint("ck_import_batch_target", type_="check")
        batch_op.create_check_constraint("ck_import_batch_target", f"target IN {_WITH_STAFF}")


def downgrade() -> None:
    # 已按规范种类落库的教职工批次必须先行归并，否则收紧约束会立刻失败。
    op.execute(
        "UPDATE import_batch SET target = 'admin_roster' "
        "WHERE target IN ('faculty_staff','class_responsibility')"
    )
    op.execute("UPDATE import_batch SET target = 'timetable' WHERE target = 'teaching_assignment'")
    with op.batch_alter_table("import_batch") as batch_op:
        with suppress(Exception):
            batch_op.drop_constraint("ck_import_batch_target", type_="check")
        batch_op.create_check_constraint("ck_import_batch_target", f"target IN {_WITHOUT_STAFF}")
