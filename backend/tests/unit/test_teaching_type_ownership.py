import pytest
from app.modules.academic.models import TeachingClass
from sqlalchemy.exc import IntegrityError

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_ownership import legacy


@pytest.fixture(name="campus")
def configured():
    yield from campus_fixture.__wrapped__()


def test_database_rejects_foreign_course_type_even_without_service(campus):
    service, db, admin, _, a, b = campus
    _, teaching, _, _ = legacy(db)
    teaching.college_id = int(a["id"])
    foreign = service.create_type(admin, int(b["id"]), {"name": "Foreign"})
    row = db.get(TeachingClass, teaching.id)
    row.course_type_id = int(foreign["id"])
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
