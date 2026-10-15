from datetime import timedelta

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


def test_as_of_uses_enrollment_scope_and_class_snapshot_not_current_projection(campus):
    config, db, admin, actor, a, b = campus
    source, target, _, _, _, student, _ = records(db, a, b)
    today = business_today()
    db.add_all([
        StudentEnrollment(student_id=student.id, administrative_class_id=source.id,
                          college_id=int(a["id"]), effective_from=today - timedelta(days=10),
                          effective_to=today, revision=1, status="ENROLLED",
                          snapshot=class_snapshot(source)),
        StudentEnrollment(student_id=student.id, administrative_class_id=target.id,
                          college_id=int(b["id"]), effective_from=today, revision=2,
                          status="ENROLLED", snapshot=class_snapshot(target)),
    ])
    source.class_name = "后来改名"
    db.commit()
    for college in (a, b):
        grant(config, admin, actor, college, ["student.read"])
    past = today - timedelta(days=1)
    result = service(db, actor, a["id"]).list_rows("students", PageParams(1, 20), as_of=past)
    assert result["total"] == 1
    row = result["items"][0]
    assert row["administrative_class_id"] == str(source.id)
    assert row["enrollment_snapshot"]["class_name"] != source.class_name
    assert row["as_of"] == past.isoformat()
    assert service(db, actor, b["id"]).list_rows("students", PageParams(1, 20), as_of=past)["total"] == 0
    assert service(db, actor, a["id"]).list_rows("students", PageParams(1, 20))["total"] == 0


def test_explicit_historical_date_does_not_invent_history_from_legacy_current_class(campus):
    config, db, admin, actor, a, b = campus
    records(db, a, b)
    grant(config, admin, actor, a, ["student.read"])
    result = service(db, actor, a["id"]).list_rows(
        "students", PageParams(1, 20), as_of=business_today() - timedelta(days=100))
    assert result["total"] == 0
