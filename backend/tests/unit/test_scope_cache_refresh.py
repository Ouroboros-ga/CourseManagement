import pytest
from app.core.exceptions import PermissionDeniedError
from app.modules.identity.models import UserAccount
from app.modules.organization.models import College
from sqlalchemy import update

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_cached_account_cannot_survive_database_disablement(campus):
    service, db, admin, teacher, a, _ = campus
    grant(service, admin, teacher, a, ["academic.read"])
    assert service.workspaces(teacher)
    db.execute(
        update(UserAccount)
        .where(UserAccount.id == teacher.id)
        .values(status="DISABLED")
        .execution_options(synchronize_session=False)
    )
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service.workspaces(teacher)


def test_college_row_read_refreshes_cached_database_status(campus):
    service, db, admin, teacher, a, _ = campus
    grant(service, admin, teacher, a, ["academic.read", "academic.manage"])
    college = service.repo.college(int(a["id"]))
    assert college.status == "ACTIVE"
    db.execute(
        update(College)
        .where(College.id == college.id)
        .values(status="INACTIVE")
        .execution_options(synchronize_session=False)
    )
    db.commit()
    assert service.repo.college(college.id).status == "INACTIVE"
