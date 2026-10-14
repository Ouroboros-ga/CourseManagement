"""Date-scoped memberships, explicit support and immutable task group/type snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1014g001"
down_revision = "f26a1014t001"
branch_labels = None
depends_on = None
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


def upgrade():
    for table, kind in [
        ("volunteer_group_member", "member"),
        ("volunteer_group_support", "support"),
    ]:
        columns = [
            sa.Column("id", ID, primary_key=True, autoincrement=True),
            sa.Column(
                "college_id", ID, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
            ),
            sa.Column(
                "group_id",
                ID,
                sa.ForeignKey("volunteer_group.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "student_id", ID, sa.ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
            ),
            sa.Column(
                "semester_id", ID, sa.ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False
            ),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("lock_version", sa.Integer(), nullable=False),
            sa.Column("created_at", DT, nullable=False),
            sa.Column("updated_at", DT, nullable=False),
            sa.CheckConstraint("effective_to > effective_from", name=f"ck_group_{kind}_dates"),
            sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name=f"ck_group_{kind}_status"),
        ]
        if kind == "support":
            columns.append(
                sa.Column(
                    "authorized_by",
                    ID,
                    sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
                    nullable=False,
                )
            )
        else:
            columns.append(
                sa.UniqueConstraint(
                    "group_id",
                    "student_id",
                    "semester_id",
                    "effective_from",
                    name="uq_group_member_start",
                )
            )
        op.create_table(
            table,
            *columns,
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_0900_ai_ci",
        )
        for col in ["college_id", "group_id", "student_id", "semester_id"]:
            op.create_index(f"ix_{table}_{col}", table, [col])
    with op.batch_alter_table("teaching_class") as batch:
        batch.add_column(sa.Column("course_type_id", ID))
        batch.add_column(
            sa.Column(
                "classification_revision", sa.Integer(), nullable=False, server_default=sa.text("1")
            )
        )
        batch.create_foreign_key(
            "fk_teaching_class_course_type",
            "course_type",
            ["course_type_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("inspection_task") as batch:
        batch.add_column(sa.Column("group_id", ID))
        batch.add_column(sa.Column("group_config_version_id", ID))
        batch.add_column(sa.Column("group_name_snapshot", sa.String(128)))
        batch.add_column(sa.Column("course_type_id_snapshot", sa.BigInteger()))
        batch.add_column(sa.Column("course_type_name_snapshot", sa.String(128)))
        batch.add_column(sa.Column("classification_revision_snapshot", sa.Integer()))
        batch.create_foreign_key(
            "fk_inspection_task_group", "volunteer_group", ["group_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_inspection_task_group_config",
            "group_config_version",
            ["group_config_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade():
    with op.batch_alter_table("inspection_task") as batch:
        batch.drop_constraint("fk_inspection_task_group", type_="foreignkey")
        batch.drop_constraint("fk_inspection_task_group_config", type_="foreignkey")
        for col in [
            "classification_revision_snapshot",
            "course_type_name_snapshot",
            "course_type_id_snapshot",
            "group_name_snapshot",
            "group_config_version_id",
            "group_id",
        ]:
            batch.drop_column(col)
    with op.batch_alter_table("teaching_class") as batch:
        batch.drop_constraint("fk_teaching_class_course_type", type_="foreignkey")
        batch.drop_column("classification_revision")
        batch.drop_column("course_type_id")
    op.drop_table("volunteer_group_support")
    op.drop_table("volunteer_group_member")
