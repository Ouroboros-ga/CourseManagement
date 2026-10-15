"""Initialize configurable college course types without classifying historical data."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015h001"
down_revision = "f26a1015g001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("course_type") as batch:
        batch.add_column(sa.Column("builtin_key", sa.String(32), nullable=True))
        batch.create_unique_constraint("uq_course_type_builtin", ["college_id", "builtin_key"])
    for key, name in (
        ("regular", "普通课"),
        ("morning_study", "早自习"),
        ("evening_study", "晚自习"),
    ):
        op.execute(
            sa.text("""UPDATE course_type SET builtin_key=:key
            WHERE normalized_name=:name AND builtin_key IS NULL""").bindparams(key=key, name=name)
        )
        op.execute(
            sa.text("""INSERT INTO course_type
            (college_id,code,builtin_key,name,normalized_name,description,display_color,
             sort_order,status,lock_version,created_at,updated_at)
            SELECT c.id,:code,:key,:name,:name,'','#409EFF',0,'ACTIVE',1,
                   CURRENT_TIMESTAMP,CURRENT_TIMESTAMP FROM college c
            WHERE NOT EXISTS (SELECT 1 FROM course_type t
                WHERE t.college_id=c.id AND t.builtin_key=:key)""").bindparams(
                code=f"builtin_{key}", key=key, name=name
            )
        )


def downgrade():
    raise RuntimeError("Retain initialized type identities; use application rollback")
