"""Independent college report keys and source revisions; legacy content stays unverified."""

from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "f26a1014r001"
down_revision = "f26a1014g001"
branch_labels = None
depends_on = None
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


@contextmanager
def preserve_sqlite_versions():
    """SQLite batch recreation drops the parent; preserve children with FKs still enabled.

    MySQL uses native ALTER. Refuse an unexpected dependent schema rather than
    silently losing a new child table when running the offline SQLite rehearsal.
    """
    if op.get_context().as_sql or op.get_bind().dialect.name != "sqlite":
        yield
        return
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    for table in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(table):
            parent = fk["referred_table"]
            if parent == "report_version" or (parent == "report" and table != "report_version"):
                raise RuntimeError("报表存在未支持的依赖表，须先扩展迁移保留策略")
    original = [column["name"] for column in inspector.get_columns("report_version")]
    connection.exec_driver_sql(
        "CREATE TEMP TABLE _r001_saved_versions AS SELECT * FROM report_version"
    )
    connection.exec_driver_sql("DELETE FROM report_version")
    yield
    remaining = {column["name"] for column in sa.inspect(connection).get_columns("report_version")}
    columns = ", ".join(
        connection.dialect.identifier_preparer.quote(name) for name in original if name in remaining
    )
    connection.exec_driver_sql(
        f"INSERT INTO report_version ({columns}) SELECT {columns} FROM _r001_saved_versions"
    )
    connection.exec_driver_sql("DROP TABLE _r001_saved_versions")


def upgrade():
    with preserve_sqlite_versions():
        _upgrade()


def _upgrade():
    # e001 already published the college-specific report key.
    with op.batch_alter_table("report_version") as batch:
        batch.add_column(sa.Column("college_id_snapshot", ID))
        batch.create_foreign_key(
            "fk_report_version_college_snapshot",
            "college",
            ["college_id_snapshot"],
            ["id"],
            ondelete="RESTRICT",
        )
    # MySQL requires an index beginning with semester_id for the existing FK.
    # Keep it available before changing a PK whose new first column is ownership.
    op.create_index(
        "ix_report_source_revision_semester_id", "report_source_revision", ["semester_id"]
    )
    with op.batch_alter_table("report_source_revision") as batch:
        batch.add_column(
            sa.Column(
                "ownership_scope_id", sa.BigInteger(), nullable=False, server_default=sa.text("0")
            )
        )
        batch.drop_constraint("pk_report_source_revision", type_="primary")
        batch.create_primary_key(
            "pk_report_source_revision", ["ownership_scope_id", "semester_id", "week_no"]
        )


def downgrade():
    if not op.get_context().as_sql:
        duplicates = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT semester_id, week_no, scope FROM report "
                    "GROUP BY semester_id, week_no, scope HAVING COUNT(*) > 1 LIMIT 1"
                )
            )
            .first()
        )
        if duplicates:
            raise RuntimeError(
                "存在多学院同周周报，不能缩回旧唯一键；须保留新结构关闭开关或恢复发布前备份"
            )
    with preserve_sqlite_versions():
        _downgrade()


def _downgrade():
    op.execute(sa.text("DELETE FROM report_source_revision WHERE ownership_scope_id <> 0"))
    with op.batch_alter_table("report_source_revision") as batch:
        batch.drop_constraint("pk_report_source_revision", type_="primary")
        batch.drop_column("ownership_scope_id")
        batch.create_primary_key("pk_report_source_revision", ["semester_id", "week_no"])
    op.drop_index("ix_report_source_revision_semester_id", table_name="report_source_revision")
    with op.batch_alter_table("report_version") as batch:
        batch.drop_constraint("fk_report_version_college_snapshot", type_="foreignkey")
        batch.drop_column("college_id_snapshot")
