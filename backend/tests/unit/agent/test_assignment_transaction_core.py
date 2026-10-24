import pytest
from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
from app.modules.inspection.models import InspectionAssignment
from sqlalchemy import select
from tests.unit.test_assignment_confirmation_plan import prepared_fixture


@pytest.fixture(name="prepared")
def fixture(monkeypatch):
    yield from prepared_fixture.__wrapped__(monkeypatch)


def test_plan_core_does_not_commit_parent_transaction(prepared):
    db, service, semester, tasks, _ = prepared
    preview = service.preview({"semester_id": str(semester.id), "task_ids": tasks})
    result = service.commit_in_transaction(
        preview["id"],
        {
            "revision": preview["revision"],
            "confirmations": preview["assigned"],
        },
    )
    assert result["assigned_count"] == 1
    assert db.scalar(select(InspectionAssignment)) is not None
    db.rollback()
    assert db.scalar(select(InspectionAssignment)) is None
    assert db.get(AssignmentConfirmationPlan, preview["id"]).status != "COMMITTED"


def test_original_commit_still_commits_and_is_idempotent(prepared):
    db, service, semester, tasks, _ = prepared
    preview = service.preview({"semester_id": str(semester.id), "task_ids": tasks})
    body = {"revision": preview["revision"], "confirmations": preview["assigned"]}
    result = service.commit(preview["id"], body)
    db.rollback()
    assert db.scalar(select(InspectionAssignment)) is not None
    assert service.commit(preview["id"], body) == result
