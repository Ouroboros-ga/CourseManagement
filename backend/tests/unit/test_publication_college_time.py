import pytest
from app.core.config import get_settings
from app.modules.academic.models import CourseScheduleWeek
from app.modules.academic.publication_service import MyAcademicSourceService
from app.modules.academic.time_service import CollegeTimeService

from tests.unit.test_academic_publication import prepare, publish
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_publication_projects_actual_college_clock_per_occurrence(campus, monkeypatch):
    db, teacher, a, _, teaching, schedule, _, user, _ = prepare(campus)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    db.add(CourseScheduleWeek(schedule_id=schedule.id, week_no=3))
    db.commit()
    times = CollegeTimeService(db, campus[2], int(a["id"]), teaching.semester_id)
    for day, hour in [("2026-09-07", "07"), ("2026-09-14", "09")]:
        body = {
            "effective_from": day,
            "calendar": [],
            "periods": [
                {"period_no": 1, "start_time": f"{hour}:00", "end_time": f"{hour}:40"},
                {"period_no": 2, "start_time": f"{hour}:50", "end_time": f"{int(hour) + 1:02}:30"},
            ],
        }
        times.publish(body, times.preview(body)["revision"])
    publish(db, teacher, a["id"], teaching.semester_id)
    entries = MyAcademicSourceService(db, user.id).initialize(teaching.semester_id)["entries"]
    assert {entry["start_time"] for entry in entries} == {"07:00:00", "09:00:00"}
    assert len(entries) == 2
    assert [entry["occurrence_dates"] for entry in entries] == [["2026-09-07"], ["2026-09-14"]]


def test_college_clock_does_not_discard_school_calendar_without_explicit_override(campus):
    from datetime import date

    from app.modules.academic.models import CalendarOverride
    from app.modules.academic.time_service import TimeResolver

    db, _, a, _, teaching, *_ = prepare(campus)
    db.add(
        CalendarOverride(
            semester_id=teaching.semester_id, date=date(2026, 9, 7), override_type="STOP"
        )
    )
    db.commit()
    service = CollegeTimeService(db, campus[2], int(a["id"]), teaching.semester_id)
    body = {
        "effective_from": "2026-09-07",
        "periods": [{"period_no": 1, "start_time": "07:00", "end_time": "07:40"}],
        "calendar": [],
    }
    service.publish(body, service.preview(body)["revision"])
    resolver = TimeResolver(db)
    resolver.prefetch(int(a["id"]), teaching.semester_id)
    assert resolver.teaching_day(int(a["id"]), teaching.semester_id, date(2026, 9, 7)) is None
    body["calendar"] = [
        {
            "date": "2026-09-07",
            "override_type": "MAKEUP",
            "source_teaching_week": 2,
            "source_teaching_weekday": 1,
        }
    ]
    service.publish(body, service.preview(body)["revision"])
    assert TimeResolver(db).teaching_day(int(a["id"]), teaching.semester_id, date(2026, 9, 7)) == (
        2,
        1,
    )
