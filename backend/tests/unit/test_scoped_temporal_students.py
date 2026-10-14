import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.enrollment_service import class_snapshot
from app.modules.identity.role_scope import business_today

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records, service


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_current_college_scope_uses_dated_enrollment_before_projection_runs(campus):
    config, db, admin, actor, a, b = campus
    _, target, _, _, _, moved, _ = records(db, a, b)
    db.add(
        StudentEnrollment(
            student_id=moved.id,
            administrative_class_id=target.id,
            college_id=int(b["id"]),
            effective_from=business_today(),
            revision=1,
            historical_confirmed=True,
            status="ENROLLED",
            snapshot=class_snapshot(target),
        )
    )
    db.commit()
    for college in (a, b):
        grant(config, admin, actor, college, ["student.read"])
    own = service(db, actor, a["id"])
    other = service(db, actor, b["id"])
    assert own.list_rows("students", PageParams(1, 20))["total"] == 0
    with pytest.raises(NotFoundError):
        own.get_row("students", moved.id)
    assert other.get_row("students", moved.id)["administrative_class_id"] == str(target.id)
