import runpy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("duplicate", [False, True])
def test_identity_migration_preflights_duplicates_without_removing_facts(duplicate):
    migration = runpy.run_path(str(Path(__file__).parents[2] /
        "migrations/versions/f26a1015u001_occurrence_identity.py"))
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE inspection_task (id INTEGER PRIMARY KEY, task_key VARCHAR(191) UNIQUE, group_id INTEGER)")
        db.exec_driver_sql("INSERT INTO inspection_task VALUES (1, 'one:group:10', 10)")
        if duplicate:
            db.exec_driver_sql("INSERT INTO inspection_task VALUES (2, 'one:group:11', 11)")
        with Operations.context(MigrationContext.configure(db)):
            if duplicate:
                with pytest.raises(RuntimeError, match="Duplicate occurrence"):
                    migration["upgrade"]()
                assert db.scalar(sa.text("SELECT COUNT(*) FROM inspection_task")) == 2
                assert db.scalar(sa.text("SELECT task_key FROM inspection_task WHERE id=1")) == "one:group:10"
            else:
                migration["upgrade"]()
                assert db.scalar(sa.text("SELECT task_key FROM inspection_task")) == "one"
                migration["downgrade"]()
                assert db.scalar(sa.text("SELECT task_key FROM inspection_task")) == "one:group:10"
