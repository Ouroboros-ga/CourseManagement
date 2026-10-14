import pytest
from app.core.exceptions import NotFoundError
from app.modules.inspection.course_occurrences import smart_sample_occurrences
from app.modules.inspection.schemas import SmartSampleRequest
from app.modules.inspection.scoped_service import ScopedInspectionService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_smart_sample_rejects_outside_class_ids_instead_of_partial_selection(campus, monkeypatch):
    from app.modules.academic.models import Student
    from sqlalchemy import select

    db, admin, a, sem, *_ = arrange(campus, monkeypatch)
    foreign = db.scalar(select(Student).where(Student.student_no == "B"))
    service = ScopedInspectionService(db, admin, int(a["id"]))
    service._require(admin.id, "inspection.generate")
    with pytest.raises(NotFoundError):
        smart_sample_occurrences(
            service,
            sem,
            SmartSampleRequest(
                semester_id=sem.id, week_no=2, target_class_ids=[foreign.administrative_class_id]
            ),
        )
