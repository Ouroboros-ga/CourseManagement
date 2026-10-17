"""Add staff binding credentials storing digests only, separate from student codes.

Plaintext codes never reach the database. Redelegation and revocation are enforced
by the application in one transaction; rollback after use must keep issued history.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1017s002"
down_revision = "f26a1017s001"
branch_labels = None
depends_on = None

OPTIONS = dict(mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")


def upgrade():
    op.create_table(
        "staff_binding_token",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "staff_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("faculty_staff.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'UNUSED'")),
        sa.Column(
            "expires_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
            nullable=False,
        ),
        sa.Column(
            "used_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
            nullable=True,
        ),
        sa.Column(
            "failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('UNUSED','USED','EXPIRED')", name="staff_binding_status"),
        **OPTIONS,
    )
    op.create_index(
        "ix_staff_binding_token_staff_id", "staff_binding_token", ["staff_id"]
    )
    op.create_index(
        "ix_staff_binding_token_token_hash", "staff_binding_token", ["token_hash"]
    )


def downgrade():
    op.drop_table("staff_binding_token")
