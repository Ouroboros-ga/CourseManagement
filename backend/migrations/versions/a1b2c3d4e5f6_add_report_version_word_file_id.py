"""Add word_file_id to report_version.

Revision ID: a1b2c3d4e5f6
Revises: e51f879a1b23
Create Date: 2026-10-10 15:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "e51f879a1b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("report_version") as batch_op:
        batch_op.add_column(
            sa.Column(
                "word_file_id",
                sa.BigInteger().with_variant(sa.INTEGER(), "sqlite"),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            op.f("fk_report_version_word_file_id_file_object"),
            "file_object",
            ["word_file_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("report_version") as batch_op:
        batch_op.drop_constraint(
            op.f("fk_report_version_word_file_id_file_object"),
            type_="foreignkey",
        )
        batch_op.drop_column("word_file_id")
