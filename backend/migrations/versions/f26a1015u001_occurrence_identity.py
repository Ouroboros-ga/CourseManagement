"""Keep one stable task identity across execution groups, without removing facts."""

import re

import sqlalchemy as sa
from alembic import op

revision = "f26a1015u001"
down_revision = "f26a1015s001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Occurrence identity migration requires a live duplicate preflight")
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT id, task_key, group_id FROM inspection_task")).all()
    identities, updates = {}, []
    for row in rows:
        key = re.sub(r":group:[0-9]+$", "", row.task_key) if row.group_id else row.task_key
        if key in identities:
            raise RuntimeError("Duplicate occurrence tasks require explicit resolution before migration")
        identities[key] = row.id
        if key != row.task_key:
            updates.append({"key": key, "id": row.id})
    if updates:
        db.execute(sa.text("UPDATE inspection_task SET task_key=:key WHERE id=:id"), updates)


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Occurrence downgrade requires a live key check")
    db = op.get_bind()
    rows = db.execute(sa.text("SELECT id, task_key, group_id FROM inspection_task")).all()
    updates = []
    for row in rows:
        if row.group_id and not row.task_key.endswith(f":group:{row.group_id}"):
            key = row.task_key + f":group:{row.group_id}"
            if len(key) > 191:
                raise RuntimeError("Legacy task key is too long; keep additive schema or restore backup")
            updates.append({"key": key, "id": row.id})
    if updates:
        db.execute(sa.text("UPDATE inspection_task SET task_key=:key WHERE id=:id"), updates)
