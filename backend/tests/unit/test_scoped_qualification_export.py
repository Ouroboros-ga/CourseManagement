from io import BytesIO

import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.export_service import CourseScheduleExportService
from app.modules.academic.models import Student
from app.modules.academic.scoped_service import ScopedAcademicService
from app.modules.academic.scoped_timetable import master_timetable
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from openpyxl import load_workbook

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_qualification_uses_student_aggregate_version_and_never_reowns_foreign_record(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, own, foreign = records(db, a, b)
    grant(config, admin, teacher, a, ["volunteer.manage"])
    service = ScopedAcademicWriteService(db, teacher, int(a["id"]))
    body = {
        "semester_id": teaching.semester_id,
        "student_id": own.id,
        "student_lock_version": own.lock_version,
        "enabled": True,
    }
    result = service.upsert_qualification(body)
    assert result["college_id"] == a["id"]
    assert result["student_lock_version"] == body["student_lock_version"] + 1
    with pytest.raises(ConflictError):
        service.upsert_qualification({**body, "enabled": False})
    with pytest.raises(NotFoundError):
        service.upsert_qualification({**body, "student_id": foreign.id})
    assert db.get(Student, own.id).lock_version == result["student_lock_version"]


def test_master_and_export_are_selected_college_scoped_before_reading_rosters(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, schedule, *_ = records(db, a, b)
    grant(config, admin, teacher, a, ["academic.read", "course_schedule.export"])
    own = ScopedAcademicService(db, teacher, int(a["id"]))
    assert master_timetable(own, teaching.semester_id)["items"][0]["id"] == str(schedule.id)
    exporter = CourseScheduleExportService(db, college_id=int(a["id"]))
    result = exporter.export(teacher.id, teaching.semester_id, [teaching.id])
    book = load_workbook(BytesIO(result), read_only=True)
    assert len(list(book.active.values)) == 2
    with pytest.raises(NotFoundError):
        exporter.export(teacher.id, teaching.semester_id, [teaching.id, 999999])
