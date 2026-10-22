"""统计只采用当前有效提交，撤回与重交不丢失历史。"""

import pytest
from app.modules.inspection.schemas import SubmissionCreateRequest, SubmissionWithdrawRequest
from app.modules.report.repository import ReportRepository

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_submission_correction_window import _submitted


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_retired_attempts_exit_statistics_and_resubmission_reenters(campus, monkeypatch):
    db, service, actor, task, first, _own = _submitted(campus, monkeypatch)
    repo = ReportRepository(db)
    window = dict(semester_id=task.semester_id, week_no=task.week_no, date_from=None, date_to=None)
    assert repo.eligible_task_ids(**window) == [task.id]
    initial_incomplete = repo.task_incomplete_flags(
        **window, page=1, page_size=20, only_current_incomplete=True,
    )[2]
    second = service.revise_submission(
        actor, int(first.id), SubmissionCreateRequest(result="NORMAL"), None,
    )
    service.withdraw_submission(
        actor, int(second.id), SubmissionWithdrawRequest(reason="重查"), None,
    )
    assert repo.eligible_task_ids(**window) == []
    rows, total, incomplete, _overdue = repo.task_incomplete_flags(
        **window, page=1, page_size=20, only_current_incomplete=True,
    )
    assert total == incomplete == initial_incomplete + 1
    assert next(row for row in rows if row["task_id"] == task.id)["current_incomplete"] is True
    third = service.create_submission(
        actor, task.id, SubmissionCreateRequest(result="NORMAL"), None,
    )
    assert third.attempt_no == 3
    assert repo.eligible_task_ids(**window) == [task.id]
    assert repo.task_incomplete_flags(
        **window, page=1, page_size=20, only_current_incomplete=True,
    )[2] == initial_incomplete
