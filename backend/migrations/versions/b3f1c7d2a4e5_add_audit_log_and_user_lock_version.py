"""add_audit_log_and_user_lock_version

Revision ID: b3f1c7d2a4e5
Revises: 2179f23fabd2
Create Date: 2026-09-20 20:10:00.000000

P1 步骤 3：新增追加型审计表 audit_log，并为 user_account 增加乐观锁列
lock_version。不修改已应用的初始迁移；仅向后兼容地 ADD COLUMN + CREATE TABLE。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'b3f1c7d2a4e5'
down_revision: str | None = '2179f23fabd2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'user_account',
        sa.Column(
            'lock_version',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
    )
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.INTEGER(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('actor_user_id', sa.BigInteger().with_variant(sa.INTEGER(), 'sqlite'), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('resource_type', sa.String(length=64), nullable=False),
        sa.Column('resource_id', sa.String(length=64), nullable=True),
        sa.Column('before_json', sa.JSON(), nullable=True),
        sa.Column('after_json', sa.JSON(), nullable=True),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=3), 'mysql'), nullable=False),
        sa.ForeignKeyConstraint(
            ['actor_user_id'],
            ['user_account.id'],
            name=op.f('fk_audit_log_actor_user_id_user_account'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci',
        mysql_engine='InnoDB',
    )
    op.create_index(
        op.f('ix_audit_log_actor_user_id'),
        'audit_log',
        ['actor_user_id'],
        unique=False,
    )


def downgrade() -> None:
    # 先整表删除（连同其索引与外键），再删除 user_account 新增列。
    # 不单独 drop_index：MySQL 不允许删除被外键依赖的索引。
    op.drop_table('audit_log')
    op.drop_column('user_account', 'lock_version')
