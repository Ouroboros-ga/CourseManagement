"""Index audit time-window pagination.

Revision ID: d42a9e6c71b0
Revises: c9b4a73e5d21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d42a9e6c71b0"
down_revision: str | None = "c9b4a73e5d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_log_created_at_id", "audit_log", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at_id", table_name="audit_log")
