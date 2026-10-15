"""Confirmed shared identities and atomic per-student inspection responsibility."""

import json
from collections import defaultdict

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "f26a1016a003"
down_revision = "f26a1016a002"
branch_labels = None
depends_on = None
OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def historical_claims(bind):
    tasks = list(
        bind.execute(
            sa.text(
                "SELECT id,college_id,inspection_date,inspection_type,course_schedule_id,"
                "teaching_class_id,administrative_class_id,start_period,end_period,"
                "roster_version,canceled_at FROM inspection_task"
            )
        ).mappings()
    )
    sources, members = defaultdict(set), defaultdict(set)
    for row in bind.execute(sa.text("SELECT task_id,course_schedule_id FROM task_schedule_source")):
        sources[row.task_id].add(row.course_schedule_id)
    for row in bind.execute(
        sa.text("SELECT task_id,roster_version,student_id FROM task_roster_member")
    ):
        members[row.task_id, row.roster_version].add(row.student_id)
    facts = set(
        bind.scalars(
            sa.text(
                "SELECT task_id FROM attendance_record UNION "
                "SELECT task_id FROM task_deadline_assessment"
            )
        )
    )
    occupied, updates, claims = {}, [], []
    for task in tasks:
        ids = sources[task["id"]] | (
            {task["course_schedule_id"]} if task["course_schedule_id"] else set()
        )
        keys = [f"s:{sid}|{task['inspection_date'].isoformat()}" for sid in sorted(ids)]
        if not keys:
            keys = [
                f"{task['inspection_type']}:a:"
                f"{task['administrative_class_id'] or task['teaching_class_id']}|"
                f"{task['inspection_date']}|{task['start_period']}-{task['end_period']}"
            ]
        updates.append({"tid": task["id"], "keys": json.dumps(keys)})
        if task["college_id"] is None or (task["canceled_at"] and task["id"] not in facts):
            continue
        for key in keys:
            for student in members[task["id"], task["roster_version"]]:
                identity = task["college_id"], key, student
                if identity in occupied and occupied[identity] != task["id"]:
                    raise RuntimeError(
                        "Existing tasks have overlapping responsibility; "
                        "resolve duplicates before migration"
                    )
                occupied[identity] = task["id"]
                claims.append(
                    {
                        "college_id": task["college_id"],
                        "occurrence_key": key,
                        "student_id": student,
                        "task_id": task["id"],
                    }
                )
    return updates, claims


def upgrade():
    bind = op.get_bind()
    # Inspect legacy responsibility BEFORE any MySQL DDL, which implicitly commits.
    updates, claims = historical_claims(bind)
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "academic_offering",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "school_id", identity, sa.ForeignKey("school.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "semester_id",
            identity,
            sa.ForeignKey("semester.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("course_name", sa.String(128), nullable=False),
        sa.Column(
            "offering_college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT")
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        **OPTIONS,
    )
    op.add_column("teaching_class", sa.Column("academic_offering_id", sa.String(32), nullable=True))
    op.create_foreign_key(
        "fk_teaching_academic_offering",
        "teaching_class",
        "academic_offering",
        ["academic_offering_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_teaching_class_academic_offering_id", "teaching_class", ["academic_offering_id"]
    )
    op.add_column("course_schedule", sa.Column("shared_meeting_key", sa.String(64), nullable=True))
    op.add_column("course_schedule", sa.Column("shared_identity_from", sa.Date(), nullable=True))
    op.add_column(
        "inspection_task", sa.Column("occurrence_keys_snapshot", sa.JSON(), nullable=True)
    )
    op.create_table(
        "import_source_assertion",
        sa.Column("id", identity, primary_key=True, autoincrement=True),
        sa.Column(
            "offering_id",
            sa.String(32),
            sa.ForeignKey("academic_offering.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "teaching_class_id",
            identity,
            sa.ForeignKey("teaching_class.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "college_id", identity, sa.ForeignKey("college.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("assertion", sa.JSON(), nullable=False),
        sa.Column(
            "confirmed_by",
            identity,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql"), nullable=False
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_import_source_assertion_teaching_class_id",
        "import_source_assertion",
        ["teaching_class_id"],
    )
    op.create_table(
        "inspection_responsibility",
        sa.Column(
            "college_id",
            identity,
            sa.ForeignKey("college.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("occurrence_key", sa.String(128), primary_key=True),
        sa.Column(
            "student_id",
            identity,
            sa.ForeignKey("student.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "task_id",
            identity,
            sa.ForeignKey("inspection_task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        **OPTIONS,
    )
    op.create_index(
        "ix_inspection_responsibility_task_id", "inspection_responsibility", ["task_id"]
    )
    for start in range(0, len(updates), 500):
        bind.execute(
            sa.text("UPDATE inspection_task SET occurrence_keys_snapshot=:keys WHERE id=:tid"),
            updates[start : start + 500],
        )
    table = sa.table(
        "inspection_responsibility",
        sa.column("college_id"),
        sa.column("occurrence_key"),
        sa.column("student_id"),
        sa.column("task_id"),
    )
    for start in range(0, len(claims), 1000):
        bind.execute(table.insert(), claims[start : start + 1000])
    op.create_unique_constraint("uq_course_college_code", "course", ["college_id", "course_code"])
    op.drop_constraint("uq_course_course_code", "course", type_="unique")


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT course_code FROM course GROUP BY course_code HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError(
            "Cross-college duplicate course codes exist; "
            "restore reviewed backup instead of destructive downgrade"
        )
    op.create_unique_constraint("uq_course_course_code", "course", ["course_code"])
    op.drop_constraint("uq_course_college_code", "course", type_="unique")
    op.drop_table("inspection_responsibility")
    op.drop_table("import_source_assertion")
    op.drop_column("inspection_task", "occurrence_keys_snapshot")
    op.drop_column("course_schedule", "shared_identity_from")
    op.drop_column("course_schedule", "shared_meeting_key")
    op.drop_constraint("fk_teaching_academic_offering", "teaching_class", type_="foreignkey")
    op.drop_index("ix_teaching_class_academic_offering_id", table_name="teaching_class")
    op.drop_column("teaching_class", "academic_offering_id")
    op.drop_table("academic_offering")
