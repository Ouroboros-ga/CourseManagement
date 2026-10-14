"""Independent college deadlines; existing tasks keep the original school policy."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "f26a1015d001"
down_revision = "f26a1014x001"
branch_labels = None
depends_on = None


@contextmanager
def preserve_children(parent):
    if op.get_context().as_sql or op.get_bind().dialect.name != "sqlite":
        yield
        return
    db = op.get_bind()
    inspector = sa.inspect(db)
    parents = {
        name: {fk["referred_table"] for fk in inspector.get_foreign_keys(name)}
        for name in inspector.get_table_names()
    }
    descendants, frontier = set(), {parent}
    while frontier:
        frontier = (
            {name for name, refs in parents.items() if refs & frontier} - descendants - {parent}
        )
        descendants |= frontier
    order = [name for name, _ in inspector.get_sorted_table_and_fkc_names() if name in descendants]
    if len(order) != len(descendants):
        raise RuntimeError("Unsupported cyclic children; migration did not rebuild the parent")
    quote = db.dialect.identifier_preparer.quote
    columns = {}
    for name in order:
        columns[name] = [c["name"] for c in inspector.get_columns(name) if not c.get("computed")]
        db.exec_driver_sql(
            f"CREATE TEMP TABLE {quote('_d001_saved_' + name)} AS SELECT * FROM {quote(name)}"
        )
    for name in reversed(order):
        db.exec_driver_sql(f"DELETE FROM {quote(name)}")
    yield
    for name in order:
        fields = ", ".join(quote(column) for column in columns[name])
        db.exec_driver_sql(
            f"INSERT INTO {quote(name)} ({fields}) SELECT {fields} FROM {quote('_d001_saved_' + name)}"
        )
        db.exec_driver_sql(f"DROP TABLE {quote('_d001_saved_' + name)}")


def upgrade():
    with preserve_children("submission_deadline_day"):
        with op.batch_alter_table("submission_deadline_day") as batch:
            batch.add_column(
                sa.Column("ownership_scope_id", sa.BigInteger(), nullable=False, server_default="0")
            )
            batch.drop_constraint("uq_submission_deadline_day_sem_date", type_="unique")
            batch.create_unique_constraint(
                "uq_deadline_scope_sem_date",
                ["ownership_scope_id", "semester_id", "inspection_date"],
            )
            batch.create_check_constraint(
                "ck_deadline_scope_nonnegative", "ownership_scope_id >= 0"
            )
    with preserve_children("inspection_task"):
        with op.batch_alter_table("inspection_task") as batch:
            batch.add_column(
                sa.Column(
                    "deadline_day_id",
                    sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                    nullable=True,
                )
            )
            batch.create_foreign_key(
                "fk_inspection_task_deadline_day_id_submission_deadline_day",
                "submission_deadline_day",
                ["deadline_day_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index("ix_inspection_task_deadline_day_id", ["deadline_day_id"])


def downgrade():
    if not op.get_context().as_sql:
        db = op.get_bind()
        if (
            db.execute(
                sa.text(
                    "SELECT id FROM submission_deadline_day WHERE ownership_scope_id <> 0 LIMIT 1"
                )
            ).first()
            or db.execute(
                sa.text("SELECT id FROM inspection_task WHERE deadline_day_id IS NOT NULL LIMIT 1")
            ).first()
        ):
            raise RuntimeError(
                "College deadline facts exist; retain this schema or restore the verified pre-upgrade backup"
            )
    with preserve_children("inspection_task"):
        with op.batch_alter_table("inspection_task") as batch:
            batch.drop_constraint(
                "fk_inspection_task_deadline_day_id_submission_deadline_day", type_="foreignkey"
            )
            batch.drop_index("ix_inspection_task_deadline_day_id")
            batch.drop_column("deadline_day_id")
    with preserve_children("submission_deadline_day"):
        with op.batch_alter_table("submission_deadline_day") as batch:
            batch.drop_constraint("uq_deadline_scope_sem_date", type_="unique")
            batch.drop_constraint("ck_deadline_scope_nonnegative", type_="check")
            batch.drop_column("ownership_scope_id")
            batch.create_unique_constraint(
                "uq_submission_deadline_day_sem_date", ["semester_id", "inspection_date"]
            )
