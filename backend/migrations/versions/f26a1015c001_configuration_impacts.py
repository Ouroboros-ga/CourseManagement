"""Durable future task decisions; no historic task snapshot is rewritten."""
import sqlalchemy as sa
from alembic import op

revision = "f26a1015c001"
down_revision = "f26a1015b001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table("configuration_impact_item",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column("college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", identity, sa.ForeignKey("inspection_task.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("decided_by", identity, sa.ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("college_id", "source_kind", "source_id", "source_version", "task_id", name="uq_configuration_impact_task"),
        sa.CheckConstraint("status IN ('OPEN','KEEP','CANCEL','REASSIGNED')", name="ck_configuration_impact_status"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")
    op.create_index("ix_configuration_impact_item_college_id", "configuration_impact_item", ["college_id"])
    op.create_index("ix_configuration_impact_item_task_id", "configuration_impact_item", ["task_id"])


def downgrade():
    if op.get_context().as_sql or op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM configuration_impact_item")):
        raise RuntimeError("Impact history exists or cannot be inspected; retain schema or restore backup")
    op.drop_table("configuration_impact_item")
