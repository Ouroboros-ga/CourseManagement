import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import CourseSchedule, Semester, TeachingClass
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_semester_reset_is_college_scoped_and_retains_shared_school_settings(campus):
    _, db, admin, _, a, b = campus
    _, _, _, teaching, schedule, own, foreign = records(db, a, b)
    sem = db.get(Semester, teaching.semester_id)
    other = TeachingClass(
        semester_id=sem.id,
        course_id=teaching.course_id,
        college_id=int(b["id"]),
        class_code="OTHER",
        class_name="乙院课",
    )
    db.add(other)
    db.commit()
    own_id, other_id = teaching.id, other.id
    service = ScopedAcademicWriteService(db, admin, int(a["id"]))
    result = service.reset_semester(
        sem.id,
        {
            "confirm_name": sem.name,
            "source_revision": service.reset_preview(sem.id)["source_revision"],
        },
    )
    assert result["cleared_tasks_count"] == 1
    assert result["cleared_schedules_count"] == 1
    assert db.get(TeachingClass, own_id, populate_existing=True) is None
    assert db.get(TeachingClass, other_id, populate_existing=True) is not None
    assert db.get(Semester, sem.id) is not None
    assert result["cleared_calendar_overrides_count"] == 0


def test_reset_rejects_cross_college_parent_corruption_without_partial_deletion(campus):
    _, db, admin, _, a, b = campus
    _, _, _, teaching, schedule, *_ = records(db, a, b)
    task = db.scalar(select(InspectionTask))
    task.college_id = int(b["id"])
    db.commit()
    sem = db.get(Semester, teaching.semester_id)
    with pytest.raises(ConflictError):
        service = ScopedAcademicWriteService(db, admin, int(a["id"]))
        service.reset_semester(
            sem.id,
            {
                "confirm_name": sem.name,
                "source_revision": service.reset_preview(sem.id)["source_revision"],
            },
        )
    assert db.get(CourseSchedule, schedule.id, populate_existing=True) is not None


def test_reset_refuses_new_facts_after_preview(campus):
    _, db, admin, _, a, b = campus
    _, _, _, teaching, _, *_ = records(db, a, b)
    sem = db.get(Semester, teaching.semester_id)
    service = ScopedAcademicWriteService(db, admin, int(a["id"]))
    preview = service.reset_preview(sem.id)
    teaching.class_name = "预览后修改"
    teaching.ownership_version += 1
    db.commit()
    with pytest.raises(ConflictError):
        service.reset_semester(
            sem.id, {"confirm_name": sem.name, "source_revision": preview["source_revision"]}
        )
    assert db.get(TeachingClass, teaching.id, populate_existing=True) is not None
