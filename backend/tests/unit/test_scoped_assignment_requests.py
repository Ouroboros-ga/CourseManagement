import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionTask,
)
from app.modules.inspection.schemas import AutoAssignRequest
from app.modules.inspection.service import InspectionService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup
from tests.unit.test_scoped_inspection_management import grant_global_permission


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_foreign_assignment_and_change_request_cannot_bypass_task_scope(campus, monkeypatch):
    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    grant_global_permission(db, "assignment.manage")
    service = InspectionService(db)
    service._require(actor.id, "assignment.manage")
    created = []
    for task in db.scalars(select(InspectionTask).order_by(InspectionTask.id)):
        assignment = InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=campus[2].id,
            assigned_by=campus[2].id,
            assign_method="MANUAL",
        )
        db.add(assignment)
        db.flush()
        request = AssignmentChangeRequest(
            assignment_id=assignment.id, request_user_id=campus[2].id, reason="test"
        )
        db.add(request)
        db.flush()
        created.append((assignment, request))
    db.commit()
    foreign, request = created[1]
    assert service._repo.get_assignment(foreign.id) is None
    assert service._repo.get_assignment_for_update(foreign.id) is None
    assert service._repo.get_change_request(request.id) is None
    assert service._repo.get_change_request_for_update(request.id) is None
    assert service._repo.get_change_request_with_task(request.id) is None
    rows, total = service._repo.list_change_requests_with_task(
        PageParams(1, 20), status=None, requester_user_id=None
    )
    assert total == len(rows) == 1


def test_explicit_mixed_auto_assign_targets_reject_whole_batch(campus, monkeypatch):
    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    grant_global_permission(db, "assignment.manage")
    service = InspectionService(db)
    service._require(actor.id, "assignment.manage")
    tasks = list(db.scalars(select(InspectionTask).order_by(InspectionTask.id)))
    with pytest.raises(NotFoundError):
        service._load_assign_targets(
            tasks[0].semester_id,
            AutoAssignRequest(
                semester_id=tasks[0].semester_id, task_ids=[str(task.id) for task in tasks]
            ),
        )
