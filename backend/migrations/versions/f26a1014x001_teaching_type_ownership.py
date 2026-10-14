"""Database defense for the teaching class's dynamic college course type."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "f26a1014x001"
down_revision = "f26a1014r001"
branch_labels = None
depends_on = None


@contextmanager
def preserve_sqlite_children():
    if op.get_context().as_sql or op.get_bind().dialect.name != "sqlite":
        yield
        return
    db = op.get_bind()
    inspector = sa.inspect(db)
    parents = {
        name: {fk["referred_table"] for fk in inspector.get_foreign_keys(name)}
        for name in inspector.get_table_names()
    }
    descendants = set()
    frontier = {"teaching_class"}
    while frontier:
        children = (
            {name for name, refs in parents.items() if refs & frontier}
            - descendants
            - {"teaching_class"}
        )
        descendants |= children
        frontier = children
    order = [name for name, _ in inspector.get_sorted_table_and_fkc_names() if name in descendants]
    if len(order) != len(descendants):
        raise RuntimeError("教学班子表存在未支持的循环依赖，不能重建")
    quote = db.dialect.identifier_preparer.quote
    columns = {}
    for name in order:
        columns[name] = [c["name"] for c in inspector.get_columns(name) if not c.get("computed")]
        db.exec_driver_sql(
            f"CREATE TEMP TABLE {quote('_x001_saved_' + name)} AS SELECT * FROM {quote(name)}"
        )
    for name in reversed(order):
        db.exec_driver_sql(f"DELETE FROM {quote(name)}")
    yield
    for name in order:
        fields = ", ".join(quote(c) for c in columns[name])
        db.exec_driver_sql(
            f"INSERT INTO {quote(name)} ({fields}) SELECT {fields} FROM {quote('_x001_saved_' + name)}"
        )
        db.exec_driver_sql(f"DROP TABLE {quote('_x001_saved_' + name)}")


def upgrade():
    if not op.get_context().as_sql:
        invalid = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT t.id FROM teaching_class t LEFT JOIN course_type c "
                    "ON c.id=t.course_type_id AND c.college_id=t.college_id "
                    "WHERE t.course_type_id IS NOT NULL AND (t.college_id IS NULL OR c.id IS NULL) LIMIT 1"
                )
            )
            .first()
        )
        if invalid:
            raise RuntimeError("教学班课程类型存在未知或跨院归属，须先核对；迁移未自动重分类")
    op.create_index(
        "ix_teaching_class_college_type", "teaching_class", ["college_id", "course_type_id"]
    )
    with preserve_sqlite_children():
        with op.batch_alter_table("teaching_class") as batch:
            batch.create_foreign_key(
                "fk_teaching_class_college_type",
                "course_type",
                ["college_id", "course_type_id"],
                ["college_id", "id"],
                ondelete="RESTRICT",
            )


def downgrade():
    with preserve_sqlite_children():
        with op.batch_alter_table("teaching_class") as batch:
            batch.drop_constraint("fk_teaching_class_college_type", type_="foreignkey")
    op.drop_index("ix_teaching_class_college_type", table_name="teaching_class")
