import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.identity.models import Permission, Role, RolePermission
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from app.modules.inspection.service import InspectionService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def grant_global_permission(db, code):
    role = db.scalar(select(Role).where(Role.code == "TEACHER_ADMIN"))
    permission = Permission(code=code, name=code)
    db.add(permission)
    db.flush()
    db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()


def test_management_submission_query_and_details_share_scope(campus, monkeypatch):
    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    grant_global_permission(db, "submission.review")
    service = InspectionService(db)
    service._require(actor.id, "submission.review")
    rows, total = service._repo.list_management_submissions(
        PageParams(1, 20),
        semester_id=None,
        date_from=None,
        date_to=None,
        task_id=None,
        review_status=None,
    )
    assert total == 1
    foreign_task = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[5]["id"]))
    )
    foreign_sub = db.scalar(
        select(InspectionSubmission).where(InspectionSubmission.task_id == foreign_task.id)
    )
    assert service._repo.get_submission(foreign_sub.id) is None
    assert service._repo.get_submission_for_update(foreign_sub.id) is None


def test_mixed_college_delete_rejects_whole_batch(campus, monkeypatch):
    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    grant_global_permission(db, "inspection.generate")
    task_ids = list(db.scalars(select(InspectionTask.id)))
    with pytest.raises(NotFoundError):
        InspectionService(db).delete_tasks(actor, task_ids)
    assert list(db.scalars(select(InspectionTask.id))) == task_ids
