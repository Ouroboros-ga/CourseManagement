"""Private import originals and their durable inspection queue receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1025a012"
down_revision = "f26a1025a011"
branch_labels = None
depends_on = None


def upgrade():
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    stamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
    columns = [sa.Column("id", pk, primary_key=True, autoincrement=True)]
    for name, target in [
        ("run_id", "agent_run"),
        ("file_id", "file_object"),
        ("actor_user_id", "user_account"),
        ("source_session_id", "auth_session"),
    ]:
        columns.append(
            sa.Column(
                name,
                sa.BigInteger(),
                sa.ForeignKey(
                    f"{target}.id",
                    ondelete="RESTRICT",
                    name=f"fk_agent_import_workspace_{name}_{target}",
                ),
                nullable=False,
            )
        )
    columns.extend(
        [
            sa.Column("request_key", sa.String(64), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("scope_hash", sa.String(64), nullable=False),
            sa.Column("state", sa.String(16), nullable=False),
            sa.Column("inspection_json", sa.JSON()),
            sa.Column("error_code", sa.String(64)),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("attempt_token", sa.String(64)),
            sa.Column("lease_until", stamp),
            sa.Column("expires_at", stamp, nullable=False),
            sa.Column("created_at", stamp, nullable=False),
            sa.Column("updated_at", stamp, nullable=False),
        ]
    )
    op.create_table(
        "agent_import_workspace",
        *columns,
        sa.UniqueConstraint("run_id", name="uq_agent_import_run"),
        sa.UniqueConstraint("file_id", name="uq_agent_import_file"),
        sa.UniqueConstraint("source_session_id", "request_key", name="uq_agent_import_request"),
        sa.CheckConstraint(
            "state IN ('QUEUED','PROCESSING','READY','FAILED','CANCELED')",
            name=op.f("ck_agent_import_workspace_state"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name=op.f("ck_agent_import_workspace_attempts"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_agent_import_queue", "agent_import_workspace", ["state", "id"])
    op.create_index(
        "ix_agent_import_owner_expiry", "agent_import_workspace", ["actor_user_id", "expires_at"]
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM agent_import_workspace LIMIT 1")).first():
        raise RuntimeError("agent_import_workspace contains source history; retain its bindings")
    op.drop_index("ix_agent_import_owner_expiry", table_name="agent_import_workspace")
    op.drop_index("ix_agent_import_queue", table_name="agent_import_workspace")
    op.drop_table("agent_import_workspace")
