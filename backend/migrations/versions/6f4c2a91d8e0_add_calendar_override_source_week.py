"""Add optional source teaching week for calendar makeups.

Revision ID: 6f4c2a91d8e0
Revises: 2658519d48fa
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "6f4c2a91d8e0"
down_revision: str | None = "2658519d48fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calendar_override", sa.Column("source_teaching_week", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_calendar_override_ck_calendar_override_source_week_positive"),
        "calendar_override",
        "source_teaching_week IS NULL OR source_teaching_week >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_calendar_override_ck_calendar_override_source_week_positive"),
        "calendar_override",
        type_="check",
    )
    op.drop_column("calendar_override", "source_teaching_week")
