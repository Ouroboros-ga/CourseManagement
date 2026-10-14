"""grant manager single objection review

Revision ID: 181729fc7239
Revises: b2c3d4e5f6a7
Create Date: 2026-10-13 23:20:15.651441

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '181729fc7239'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 已有数据库同步负责人默认权限；不改账号个人授权及审核历史。
    op.execute(sa.text("""
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r CROSS JOIN permission p
        WHERE r.code = 'STUDENT_AFFAIRS_MANAGER' AND p.code = 'objection.final_review'
        AND NOT EXISTS (
            SELECT 1 FROM role_permission rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
        )
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM role_permission
        WHERE role_id IN (SELECT id FROM role WHERE code = 'STUDENT_AFFAIRS_MANAGER')
        AND permission_id IN (SELECT id FROM permission WHERE code = 'objection.final_review')
    """))
