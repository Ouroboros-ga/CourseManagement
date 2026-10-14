from datetime import date

import pytest
from app.core.exceptions import ConflictError, NotFoundError

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def configuration(day="2026-09-07", start="07:00", end="07:40"):
    return {
        "effective_from": day,
        "periods": [{"period_no": 1, "start_time": start, "end_time": end}],
        "calendar": [],
    }


def test_colleges_resolve_different_times_and_frozen_interval_does_not_drift(campus):
    from app.modules.academic.time_service import CollegeTimeService, TimeResolver

    config, db, admin, teacher, a, b = campus
    semester, *_ = records(db, a, b)
    publisher = CollegeTimeService(db, admin, int(a["id"]), semester.id)
    body = configuration()
    preview = publisher.preview(body)
    publisher.publish(body, preview["revision"])
    other = CollegeTimeService(db, admin, int(b["id"]), semester.id)
    body_b = configuration(start="08:00", end="08:40")
    other.publish(body_b, other.preview(body_b)["revision"])
    resolver = TimeResolver(db)
    frozen = resolver.interval(int(a["id"]), semester.id, date(2026, 9, 7), 1, 1)
    assert frozen["start_minute"] == 420 and frozen["end_minute"] == 460
    assert (
        resolver.interval(int(b["id"]), semester.id, date(2026, 9, 7), 1, 1)["start_minute"] == 480
    )
    new_body = configuration(start="09:00", end="09:40")
    publisher.publish(new_body, publisher.preview(new_body)["revision"])
    assert (
        resolver.interval(int(a["id"]), semester.id, date(2026, 9, 7), 1, 1)["start_minute"] == 540
    )
    assert frozen["start_minute"] == 420
    assert len(publisher.versions()) == 2


def test_preview_revision_rejects_changed_source_and_foreign_scope(campus):
    from app.modules.academic.time_service import CollegeTimeService

    config, db, admin, teacher, a, b = campus
    semester, *_ = records(db, a, b)
    service = CollegeTimeService(db, admin, int(a["id"]), semester.id)
    body = configuration()
    revision = service.preview(body)["revision"]
    newer = configuration(start="08:00", end="08:40")
    service.publish(newer, service.preview(newer)["revision"])
    with pytest.raises(ConflictError):
        service.publish(body, revision)
    with pytest.raises(NotFoundError):
        CollegeTimeService(db, teacher, int(b["id"]), semester.id).preview(body)


def test_calendar_stop_makeup_and_missing_period_are_explicit(campus):
    from app.modules.academic.time_service import CollegeTimeService, TimeResolver

    _, db, admin, _, a, b = campus
    semester, *_ = records(db, a, b)
    service = CollegeTimeService(db, admin, int(a["id"]), semester.id)
    body = configuration()
    body["calendar"] = [
        {"date": "2026-09-08", "override_type": "STOP"},
        {
            "date": "2026-09-09",
            "override_type": "MAKEUP",
            "source_teaching_week": 1,
            "source_teaching_weekday": 1,
        },
    ]
    service.publish(body, service.preview(body)["revision"])
    resolver = TimeResolver(db)
    assert resolver.teaching_day(int(a["id"]), semester.id, date(2026, 9, 8)) is None
    assert resolver.teaching_day(int(a["id"]), semester.id, date(2026, 9, 9)) == (1, 1)
    with pytest.raises(ConflictError):
        resolver.interval(int(a["id"]), semester.id, date(2026, 9, 7), 1, 2)
