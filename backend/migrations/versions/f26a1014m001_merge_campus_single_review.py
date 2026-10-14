"""Converge published campus and single-review histories without changing either.

The merge has no DDL or data operations. Upgrade from either branch runs only
the missing branch before stamping this common head.
"""
revision = "f26a1014m001"
down_revision = ("f26a1013c002", "181729fc7239")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
