import pytest
from app.core.exceptions import NotFoundError
from app.modules.academic.models import Course, CourseSchedule, TeachingClassStudent
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_elective_batch_is_atomic_scoped_and_retry_does_not_duplicate(campus):
    _, db, admin, _, a, b = campus
    _, _, _, teaching, _, own, foreign = records(db, a, b)
    service = ScopedAcademicWriteService(db, admin, int(a["id"]))
    body = {
        "semester_id": str(teaching.semester_id),
        "course_name": "独立选修",
        "teaching_classes": [
            {
                "class_code": "OPTIONAL-A",
                "weekday": 1,
                "start_period": 1,
                "end_period": 2,
                "weeks": [1, 2],
                "student_nos": [own.student_no, foreign.student_no],
            }
        ],
    }
    with pytest.raises(NotFoundError):
        service.batch_elective(body)
    assert (
        db.scalar(select(func.count()).select_from(Course).where(Course.course_name == "独立选修"))
        == 0
    )
    body["teaching_classes"][0]["student_nos"] = [own.student_no]
    first = service.batch_elective(body)
    second = service.batch_elective(body)
    assert first["teaching_classes_created"] == 1
    assert second["teaching_classes_created"] == second["schedules_created"] == 0
    assert db.scalar(select(func.count()).select_from(CourseSchedule)) == 2
    assert list(db.scalars(select(TeachingClassStudent.student_id))) == [own.id]
