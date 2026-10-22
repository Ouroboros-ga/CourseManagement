"""The integration probe must not confuse global and college source revisions."""

import pytest
from app.modules.report.models import ReportSourceRevision

from tests.integration.test_inspection_review_attendance import _report_revision
from tests.integration.test_report_source_revision import _revision
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_submission_correction_window import _submitted


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_revision_probe_selects_global_scope_when_college_revision_also_exists(campus, monkeypatch):
    db, _service, _actor, task, _first, _own = _submitted(campus, monkeypatch)
    db.add_all([
        ReportSourceRevision(semester_id=task.semester_id, week_no=task.week_no,
                             ownership_scope_id=0, revision=3),
        ReportSourceRevision(semester_id=task.semester_id, week_no=task.week_no,
                             ownership_scope_id=task.college_id, revision=7),
    ])
    db.commit()
    assert _report_revision(db, task.semester_id, task.id) == 3
    assert _revision(db, task.semester_id, task.week_no) == 3
