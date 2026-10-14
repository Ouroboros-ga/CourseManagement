import pytest
from app.modules.inspection.models import InspectionTask
from app.modules.report.source_revision import SourceRevisionService
from sqlalchemy import select
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import Insert

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_fact_change_bumps_its_college_and_legacy_school_revision_only(campus, monkeypatch):
    db, _, a, b, own, _ = prepare(campus)
    task = db.scalar(select(InspectionTask).where(InspectionTask.id == own.task_id))
    statements = []
    execute = db.execute

    def capture(statement, *args, **kwargs):
        if isinstance(statement, Insert):
            statements.append(statement.compile(dialect=mysql.dialect()).params)
            return None
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", capture)
    SourceRevisionService.bump_for_task_id(db, task.id)
    assert [s["ownership_scope_id"] for s in statements] == [0, int(a["id"])]
    assert all(
        s["semester_id"] == task.semester_id and s["week_no"] == task.week_no for s in statements
    )
    assert int(b["id"]) not in [s["ownership_scope_id"] for s in statements]
