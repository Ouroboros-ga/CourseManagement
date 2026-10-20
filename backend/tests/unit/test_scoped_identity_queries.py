import pytest
from app.common.pagination import PageParams
from app.core.config import get_settings
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.identity.account_service import AccountService
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import IdentityService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_role_targets_and_account_counts_use_explicit_college_sql(campus, monkeypatch):
    _, db, admin, teacher, a, b = campus
    *_, own, foreign = records(db, a, b)
    sync_registry(db)
    role = db.scalar(select(Role).where(Role.code == "TEACHER_ADMIN"))
    manager = db.scalar(select(Role).where(Role.code == "STUDENT_AFFAIRS_MANAGER"))
    own_user = UserAccount(display_name="本院负责人", student_id=own.id)
    other_user = UserAccount(display_name="外院负责人", student_id=foreign.id)
    db.add_all([own_user, other_user])
    db.flush()
    db.add_all(
        [
            UserRole(user_id=teacher.id, role_id=role.id),
            UserRole(user_id=own_user.id, role_id=manager.id),
            UserRole(user_id=other_user.id, role_id=manager.id),
            TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])),
        ]
    )
    db.commit()
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    targets, _ = IdentityService(db).list_role_assignment_targets(teacher.id)
    assert str(own_user.id) in {row.id for row in targets}
    assert str(other_user.id) not in {row.id for row in targets}
    subset, _ = IdentityService(db).list_role_assignment_targets(
        teacher.id, student_ids=[own.id, foreign.id]
    )
    assert [row.id for row in subset] == [str(own_user.id)]
    hidden, _ = IdentityService(db).list_role_assignment_targets(
        teacher.id, student_ids=[foreign.id]
    )
    assert hidden == []
    page = IdentityService(db).role_assignment_target_page(
        teacher.id, PageParams(1, 50), role_code="STUDENT_AFFAIRS_MANAGER", keyword="负责人"
    )
    assert page["total"] == 1 and page["items"][0]["id"] == str(own_user.id)
    assert (
        IdentityService(db).role_assignment_target_page(
            teacher.id, PageParams(1, 50), student_candidates=True
        )["total"]
        == 0
    )
    accounts = AccountService(db).list_accounts(teacher, PageParams(1, 20), None, None)
    assert accounts["total"] == 2
    teachers = AccountService(db).list_accounts(
        teacher, PageParams(1, 50), None, None, role_codes=["SUPER_ADMIN", "TEACHER_ADMIN"]
    )
    assert teachers["total"] == 1
    assert teachers["items"][0]["id"] == str(teacher.id)
    assert {row["id"] for row in accounts["items"]} == {str(teacher.id), str(own_user.id)}
