"""Personal recovery/exceptions and explicit school summary permission."""

import sqlalchemy as sa
from alembic import op

revision = "f26a1015g001"
down_revision = "f26a1015f001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("personal_timetable", sa.Column("deleted_entries", sa.JSON(), nullable=True, server_default=sa.text("('[]')")))
    op.add_column(
        "personal_timetable", sa.Column("occurrence_exceptions", sa.JSON(), nullable=True, server_default=sa.text("('{}')"))
    )
    op.execute(
        sa.text("UPDATE personal_timetable SET deleted_entries='[]', occurrence_exceptions='{}'")
    )
    with op.batch_alter_table("personal_timetable") as batch:
        batch.alter_column("deleted_entries", existing_type=sa.JSON(), nullable=False, server_default=sa.text("('[]')"))
        batch.alter_column("occurrence_exceptions", existing_type=sa.JSON(), nullable=False, server_default=sa.text("('{}')"))
    op.execute(
        sa.text("""INSERT INTO permission (code,name,created_at,updated_at)
        SELECT 'statistics.school.read','全校汇总查看',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code='statistics.school.read')""")
    )
    op.execute(
        sa.text("""INSERT INTO role_permission (role_id,permission_id)
        SELECT r.id,p.id FROM role r CROSS JOIN permission p
        WHERE r.code='SUPER_ADMIN' AND p.code='statistics.school.read'
        AND NOT EXISTS (SELECT 1 FROM role_permission rp
            WHERE rp.role_id=r.id AND rp.permission_id=p.id)""")
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Inspect personal facts and grants before downgrade")
    db = op.get_bind()
    for deleted, exceptions in db.execute(
        sa.text("SELECT deleted_entries,occurrence_exceptions FROM personal_timetable")
    ):
        import json

        if json.loads(deleted) or json.loads(exceptions):
            raise RuntimeError("Personal recovery/exception facts exist; retain schema")
    if db.scalar(
        sa.text("""SELECT COUNT(*) FROM user_permission up JOIN permission p
        ON p.id=up.permission_id WHERE p.code='statistics.school.read'""")
    ):
        raise RuntimeError("School summary grants exist; retain permission and schema")
    with op.batch_alter_table("personal_timetable") as batch:
        batch.drop_column("occurrence_exceptions")
        batch.drop_column("deleted_entries")
    # Permission registry rows are additive; application rollback need not erase them.
