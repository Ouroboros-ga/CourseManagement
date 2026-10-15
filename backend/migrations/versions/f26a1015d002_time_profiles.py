"""Named drafts and explicit teaching-class time bindings; defaults stay compatible."""
import sqlalchemy as sa
from alembic import op

revision = "f26a1015d002"
down_revision = "f26a1015c001"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table("college_time_profile",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column("college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("semester_id", identity, sa.ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128, collation="utf8mb4_bin").with_variant(sa.String(128), "sqlite"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("draft_configuration", sa.JSON(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("college_id", "semester_id", "normalized_name", name="uq_college_time_profile_name"),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')", name="ck_college_time_profile_status"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_0900_ai_ci")
    op.create_index("ix_college_time_profile_college_id", "college_time_profile", ["college_id"])
    op.create_index("ix_college_time_profile_semester_id", "college_time_profile", ["semester_id"])
    for table, column, name in (("college_time_version", "profile_id", "fk_college_time_version_profile"),
                                 ("teaching_class", "time_profile_id", "fk_teaching_class_time_profile")):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, identity, nullable=True))
            batch.create_foreign_key(name, "college_time_profile", [column], ["id"], ondelete="RESTRICT")
            batch.create_index(f"ix_{table}_{column}", [column])


def downgrade():
    if op.get_context().as_sql or op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM college_time_profile")):
        raise RuntimeError("Named time profiles exist; retain schema or restore verified backup")
    for table, column, name in (("teaching_class", "time_profile_id", "fk_teaching_class_time_profile"),
                                 ("college_time_version", "profile_id", "fk_college_time_version_profile")):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.drop_index(f"ix_{table}_{column}")
            batch.drop_column(column)
    op.drop_table("college_time_profile")
