import pytest
from app.common.pagination import PageParams
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.identity.models import Permission, Role, RolePermission, UserRole
from app.modules.inspection.service import InspectionService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def setup(campus, monkeypatch):
    db, teacher, a, b, own, foreign = prepare(campus)
    role = Role(code="TEACHER_ADMIN", name="teacher")
    db.add(role)
    db.flush()
    for code in ["inspection.read", "inspection.roster.read"]:
        p = Permission(code=code, name=code)
        db.add(p)
        db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=p.id))
    db.add_all(
        [
            UserRole(user_id=teacher.id, role_id=role.id),
            TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])),
        ]
    )
    db.commit()
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    return db, teacher, a, b, own, foreign


def test_existing_task_read_and_count_are_college_scoped(campus, monkeypatch):
    db, teacher, a, b, own, foreign = setup(campus, monkeypatch)
    service = InspectionService(db)
    rows, total = service._repo.list_tasks(
        PageParams(1, 20), scope_filter=service._scope_filter(teacher)
    )
    assert total == 1 and [r.id for r in rows] == [own.task_id]
    with pytest.raises(NotFoundError):
        service.get_task(teacher, foreign.task_id)
    with pytest.raises(NotFoundError):
        service.get_roster(teacher, foreign.task_id, None)


def test_task_read_cross_grant_does_not_grant_roster(campus, monkeypatch):
    db, teacher, a, b, own, foreign = setup(campus, monkeypatch)
    config, _, admin, _, _, _ = campus
    grant(config, admin, teacher, b, ["inspection.read"])
    service = InspectionService(db)
    rows, total = service._repo.list_tasks(
        PageParams(1, 20), scope_filter=service._scope_filter(teacher)
    )
    assert total == 2
    with pytest.raises(NotFoundError):
        service.get_roster(teacher, foreign.task_id, None)
