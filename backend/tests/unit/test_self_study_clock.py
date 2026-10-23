"""自习时段独立于教学节次，验证事务、时间快照与重复生成边界。"""

from datetime import date, time

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError
from app.modules.academic.models import CourseSchedule, PeriodDefinition, TeachingClass
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from app.modules.academic.time_service import TimeResolver
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def campus_setup():
    yield from campus_fixture.__wrapped__()


def prepare(campus, monkeypatch):
    _, db, actor, _, a, b = campus
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    ac, _, _, teaching, _, _, _ = records(db, a, b)
    db.add(
        PeriodDefinition(
            semester_id=teaching.semester_id,
            period_no=1,
            start_time=time(8, 10),
            end_time=time(8, 55),
        )
    )
    db.commit()
    return (
        db,
        ScopedAcademicWriteService(db, actor, int(a["id"])),
        {
            "semester_id": teaching.semester_id,
            "study_type": "EARLY",
            "class_ids": [ac.id],
            "weeks": [1, 2],
            "weekdays": [1],
            "start_time": "07:30",
            "end_time": "07:50",
        },
    )


def test_clock_study_keeps_school_period_and_resolves_own_time(campus, monkeypatch):
    db, service, body = prepare(campus, monkeypatch)
    first = service.batch_self_study(body)
    again = service.batch_self_study(body)
    assert first["schedules_created"] == 1 and again["schedules_created"] == 0
    teaching = db.scalar(select(TeachingClass).where(TeachingClass.time_profile_id.is_not(None)))
    assert teaching is not None
    resolver = TimeResolver(db)
    actual = resolver.interval(
        service.college_id,
        body["semester_id"],
        date(2026, 9, 7),
        1,
        1,
        teaching_class_id=teaching.id,
    )
    assert (actual["start_minute"], actual["end_minute"]) == (450, 470)
    assert actual["time_basis"] == "CLOCK"
    ordinary = resolver.interval(service.college_id, body["semester_id"], date(2026, 9, 7), 1, 1)
    assert ordinary["start_minute"] == 490 and ordinary["time_basis"] == "PERIODS"
    assert db.scalar(select(PeriodDefinition).where(PeriodDefinition.period_no == 13)) is None
    assert first["time_label"] == "07:30—07:50"


@pytest.mark.parametrize(
    "change",
    [
        {"start_time": "08:00", "end_time": "07:50"},
        {"start_time": "07:30:30"},
        {"weeks": [61]},
        {"weekdays": [0]},
        {"start_time": None},
    ],
)
def test_bad_clock_batch_rolls_back(campus, monkeypatch, change):
    db, service, body = prepare(campus, monkeypatch)
    before = len(list(db.scalars(select(CourseSchedule))))
    with pytest.raises(AppError):
        service.batch_self_study({**body, **change})
    assert len(list(db.scalars(select(CourseSchedule)))) == before


def test_changed_time_does_not_silently_add_or_retime(campus, monkeypatch):
    _, service, body = prepare(campus, monkeypatch)
    service.batch_self_study(body)
    with pytest.raises(ConflictError, match="已有自习"):
        service.batch_self_study({**body, "start_time": "07:35"})


def test_legacy_undefined_period_rejected(campus, monkeypatch):
    _, service, body = prepare(campus, monkeypatch)
    body.pop("start_time")
    body.pop("end_time")
    with pytest.raises(AppError):
        service.batch_self_study({**body, "start_period": 60, "end_period": 60})


def test_generated_occurrence_and_task_keep_clock_snapshot(campus, monkeypatch):
    from app.modules.academic.models import Semester
    from app.modules.inspection.course_occurrences import list_occurrences
    from app.modules.inspection.models import InspectionTask
    from app.modules.inspection.schemas import CourseOccurrenceScope
    from app.modules.inspection.service import InspectionService
    from app.modules.inspection.task_time import freeze_time, task_minutes

    db, service, body = prepare(campus, monkeypatch)
    service.batch_self_study(body)
    teaching = db.scalar(select(TeachingClass).where(TeachingClass.time_profile_id.is_not(None)))
    inspection = InspectionService(db)
    semester = db.get(Semester, body["semester_id"])
    scope = CourseOccurrenceScope(
        teaching_class_ids=[teaching.id], date_from=date(2026, 9, 7), date_to=date(2026, 9, 7)
    )
    listed = list_occurrences(inspection, semester, scope, page=1, page_size=50)
    assert listed["total"] == 1
    assert listed["items"][0]["time_label"] == "07:30—07:50"
    assert listed["items"][0]["time_basis"] == "CLOCK"
    task = db.scalar(select(InspectionTask))
    task.teaching_class_id = teaching.id
    task.inspection_date = date(2026, 9, 7)
    task.start_period = task.end_period = 1
    freeze_time(db, task)
    assert task_minutes(task) == (450, 470)
    assert task.time_snapshot["time_basis"] == "CLOCK"
    assert task.time_snapshot["time_label"] == "07:30—07:50"
    # 学校第1节变化不会改变已冻结的自习时间，也不会改变自习解析。
    school = db.scalar(select(PeriodDefinition))
    school.start_time = time(8, 20)
    assert task_minutes(task) == (450, 470)


def test_clock_study_export_uses_clock_strings_not_school_period_one(campus, monkeypatch):
    from io import BytesIO

    from app.modules.academic.export_service import CourseScheduleExportService
    from app.modules.identity.seed import sync_registry
    from openpyxl import load_workbook

    db, service, body = prepare(campus, monkeypatch)
    service.batch_self_study(body)
    sync_registry(db)
    teaching = db.scalar(select(TeachingClass).where(TeachingClass.time_profile_id.is_not(None)))
    blob = CourseScheduleExportService(db, college_id=service.college_id).export(
        service.actor.id, body["semester_id"], [teaching.id]
    )
    workbook = load_workbook(BytesIO(blob), read_only=True)
    row = list(workbook.active.values)[1]
    assert row[5:7] == ("07:30", "07:50")


def test_publication_marks_clock_source_without_touching_personal_copy(campus, monkeypatch):
    from app.modules.academic.publication_models import PublishedSchedule
    from app.modules.academic.publication_service import AcademicPublicationService

    db, service, body = prepare(campus, monkeypatch)
    service.batch_self_study(body)
    publisher = AcademicPublicationService(db, service.actor, service.college_id)
    preview = publisher.preview(body["semester_id"])
    publisher.publish(body["semester_id"], preview["source_revision"])
    snapshot = db.scalar(select(PublishedSchedule)).snapshot
    assert snapshot["time_basis"] == "CLOCK"
    assert snapshot["time_label"] == "07:30—07:50"
    assert snapshot["start_time"] == "07:30:00"


def test_clock_profile_cannot_be_reinterpreted_as_school_periods(campus, monkeypatch):
    from app.modules.academic.time_models import CollegeTimeProfile
    from app.modules.academic.time_profiles import TimeProfileService

    db, service, body = prepare(campus, monkeypatch)
    service.batch_self_study(body)
    profile = db.scalar(select(CollegeTimeProfile))
    api = TimeProfileService(db, service.actor, service.college_id, body["semester_id"])
    configuration = {**profile.draft_configuration, "time_basis": "PERIODS"}
    with pytest.raises(ConflictError, match="时间来源"):
        api.save(
            profile.id,
            {
                "name": profile.name,
                "lock_version": profile.lock_version,
                "configuration": configuration,
            },
        )
