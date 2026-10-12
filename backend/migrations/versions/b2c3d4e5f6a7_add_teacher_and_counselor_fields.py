"""Add teacher and counselor fields to administrative_class, teaching_class, course_schedule, and inspection_task.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-11 13:15:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("administrative_class") as batch_op:
        batch_op.add_column(
            sa.Column("head_teacher", sa.String(64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("counselor", sa.String(64), nullable=True)
        )

    with op.batch_alter_table("teaching_class") as batch_op:
        batch_op.add_column(
            sa.Column("teacher_name", sa.String(128), nullable=True)
        )

    with op.batch_alter_table("course_schedule") as batch_op:
        batch_op.add_column(
            sa.Column("teacher", sa.String(128), nullable=True)
        )

    with op.batch_alter_table("inspection_task") as batch_op:
        batch_op.add_column(
            sa.Column("teacher_name_snapshot", sa.String(128), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("inspection_task") as batch_op:
        batch_op.drop_column("teacher_name_snapshot")

    with op.batch_alter_table("course_schedule") as batch_op:
        batch_op.drop_column("teacher")

    with op.batch_alter_table("teaching_class") as batch_op:
        batch_op.drop_column("teacher_name")

    with op.batch_alter_table("administrative_class") as batch_op:
        batch_op.drop_column("counselor")
        batch_op.drop_column("head_teacher")
