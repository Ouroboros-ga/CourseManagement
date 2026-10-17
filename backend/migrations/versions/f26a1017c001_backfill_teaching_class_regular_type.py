"""Backfill existing teaching classes with default regular course_type for their college."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1017c001"
down_revision = "f26a1017a001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # 存量教学班如果 course_type_id 为空，自动匹配其所属学院的默认“普通课”（builtin_key = 'regular' 且 status = 'ACTIVE'）
    if bind.dialect.name == "sqlite":
        bind.execute(
            sa.text(
                """
                UPDATE teaching_class
                SET course_type_id = (
                    SELECT ct.id FROM course_type ct
                    WHERE ct.college_id = COALESCE(teaching_class.college_id, 1)
                      AND ct.builtin_key = 'regular'
                      AND ct.status = 'ACTIVE'
                    LIMIT 1
                ),
                college_id = COALESCE(teaching_class.college_id, 1)
                WHERE course_type_id IS NULL
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                UPDATE teaching_class tc
                JOIN course_type ct ON ct.college_id = COALESCE(tc.college_id, 1) AND ct.builtin_key = 'regular' AND ct.status = 'ACTIVE'
                SET tc.course_type_id = ct.id,
                    tc.college_id = COALESCE(tc.college_id, 1)
                WHERE tc.course_type_id IS NULL
                """
            )
        )


def downgrade():
    pass
