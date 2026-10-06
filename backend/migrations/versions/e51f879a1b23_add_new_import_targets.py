"""Add new import targets to import_batch.

Revision ID: e51f879a1b23
Revises: d42a9e6c71b0
Create Date: 2026-10-06 23:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e51f879a1b23"
down_revision: str | None = "d42a9e6c71b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ALLOWED = "('roster','timetable','volunteer','admin_roster','grid_timetable','elective_course')"
_OLD_ALLOWED = "('roster','timetable','volunteer')"


def upgrade() -> None:
    # 扩大 target 列宽度到 32
    with op.batch_alter_table("import_batch") as batch_op:
        batch_op.alter_column("target", type_=sa.String(32), existing_type=sa.String(16), nullable=False)
        try:
            batch_op.drop_constraint("ck_import_batch_target", type_="check")
        except Exception:
            pass
        batch_op.create_check_constraint("ck_import_batch_target", f"target IN {_NEW_ALLOWED}")


def downgrade() -> None:
    with op.batch_alter_table("import_batch") as batch_op:
        try:
            batch_op.drop_constraint("ck_import_batch_target", type_="check")
        except Exception:
            pass
        batch_op.create_check_constraint("ck_import_batch_target", f"target IN {_OLD_ALLOWED}")
        batch_op.alter_column("target", type_=sa.String(16), existing_type=sa.String(32), nullable=False)
