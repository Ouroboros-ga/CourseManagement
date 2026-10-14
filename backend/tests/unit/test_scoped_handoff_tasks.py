import pytest
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.identity.models import Role, UserRole
from app.modules.identity.seed import sync_registry
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_handoff_list_and_review_cannot_use_foreign_task_ids(campus):
    db, teacher, a, b, own, foreign = prepare(campus)
    sync_registry(db)
    db.add_all(
        [
            UserRole(
                user_id=teacher.id,
                role_id=db.scalar(select(Role.id).where(Role.code == "TEACHER_ADMIN")),
            ),
            TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])),
        ]
    )
    for task in db.scalars(select(InspectionTask)):
        task.roster_review_required = True
    db.commit()
    result = EnrollmentService(db).handoff_tasks(teacher.id)
    assert [row["id"] for row in result["items"]] == [str(own.task_id)]
    task = db.get(InspectionTask, foreign.task_id)
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        EnrollmentService(db).review_task(
            teacher.id, task.id, task.lock_version, confirm_roster=True, confirm_expected_count=True
        )
    assert db.get(InspectionTask, task.id, populate_existing=True).roster_review_required
    selected = EnrollmentService(db, college_id=int(a["id"])).handoff_tasks(campus[2].id)
    assert [row["id"] for row in selected["items"]] == [str(own.task_id)]
