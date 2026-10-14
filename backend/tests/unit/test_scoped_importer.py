from io import BytesIO

import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester, Student, VolunteerQualification
from app.modules.importer.models import ImportBatch
from app.modules.importer.scoped_service import ScopedImporterService
from openpyxl import Workbook
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def configured():
    yield from campus_fixture.__wrapped__()


def sheet(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, own, foreign = records(db, a, b)
    grant(config, admin, teacher, a, ["import.execute", "volunteer.manage"])
    return ScopedImporterService(db, teacher, int(a["id"])), db, own, foreign, teaching.semester_id


def preview(service, semester_id, student_no):
    return service.create_preview(
        service.actor,
        target="volunteer",
        content=sheet([["学号", "是否启用"], [student_no, "是"]]),
        semester_id=semester_id,
        teaching_class_id=None,
        filename="fixture.xlsx",
        replace=False,
        request_id=None,
    )


def test_foreign_cached_student_is_not_importable_and_batch_scope_is_fixed(campus):
    service, db, own, foreign, sid = prepare(campus)
    db.get(Student, foreign.id)
    result = preview(service, sid, foreign.student_no)
    assert not result.can_confirm and result.errors
    batch = db.get(ImportBatch, int(result.id))
    assert batch.college_id == service.cid
    assert "college_query_scope" not in db.info
    foreign_service = ScopedImporterService(db, campus[2], int(campus[5]["id"]))
    with pytest.raises(NotFoundError):
        foreign_service.get_batch(campus[2], batch.id)


def test_source_change_rejects_confirm_atomically_and_unchanged_source_applies(campus):
    service, db, own, _, sid = prepare(campus)
    first = preview(service, sid, own.student_no)
    assert first.can_confirm
    own.name = "updated fixture"
    own.lock_version += 1
    db.commit()
    with pytest.raises(ConflictError):
        service.confirm(service.actor, int(first.id), None)
    assert (
        db.scalar(
            select(VolunteerQualification.id).where(VolunteerQualification.student_id == own.id)
        )
        is None
    )
    assert db.get(ImportBatch, int(first.id)).status == "PREVIEW"
    current = preview(service, sid, own.student_no)
    result = service.confirm(service.actor, int(current.id), None)
    assert result.status == "CONFIRMED"
    qualification = db.scalar(
        select(VolunteerQualification).where(VolunteerQualification.student_id == own.id)
    )
    assert qualification.enabled and qualification.college_id == service.cid
    assert "college_query_scope" not in db.info


def test_grid_import_uses_explicit_mapping_and_validates_actual_time_before_writing(
    campus, monkeypatch
):
    from app.core.config import get_settings
    from app.modules.academic.models import CourseSchedule
    from app.modules.academic.time_service import CollegeTimeService

    service, db, own, _, sid = prepare(campus)
    grant(campus[0], campus[2], service.actor, campus[4], ["course_schedule.import"])
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    monkeypatch.setattr(
        "app.modules.importer.service.load_grid",
        lambda content: (
            db.get(Student, own.id).administrative_class.class_name,
            [
                {
                    "course_name": "fixture mapped course",
                    "weekday": "周一",
                    "weeks": "1-2",
                    "period": "1-2",
                    "location": "fixture room",
                }
            ],
        ),
    )
    args = dict(
        target="grid_timetable",
        content=b"fixture",
        semester_id=sid,
        teaching_class_id=None,
        filename="fixture.xlsx",
        replace=False,
        request_id=None,
    )
    assert not service.create_preview(service.actor, **args).can_confirm
    semester = db.get(Semester, sid)
    time = CollegeTimeService(db, campus[2], service.cid, sid)
    body = {
        "effective_from": semester.start_date.isoformat(),
        "periods": [
            {"period_no": 1, "start_time": "07:00", "end_time": "07:40"},
            {"period_no": 2, "start_time": "08:00", "end_time": "09:30"},
        ],
        "grid_slot_mapping": {"1": 2, "2": 2},
    }
    time.publish(body, time.preview(body)["revision"])
    previewed = service.create_preview(service.actor, **args)
    assert previewed.can_confirm
    batch = db.get(ImportBatch, int(previewed.id))
    assert batch.payload_json["courses"][0]["start_period"] == 2
    service.confirm(service.actor, batch.id, None)
    inserted = list(
        db.scalars(select(CourseSchedule).where(CourseSchedule.classroom == "fixture room"))
    )
    assert len(inserted) == 1 and inserted[0].start_period == 2
