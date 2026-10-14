from datetime import date

import pytest
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.modules.academic.time_schemas import TimeConfiguration
from app.modules.inspection.models import InspectionTask

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


def test_grid_mapping_uses_configured_periods_and_rejects_ambiguous_order():
    body = configuration()
    body["periods"].append({"period_no": 2, "start_time": "08:00", "end_time": "08:45"})
    body["grid_slot_mapping"] = {"1": 2, "2": 2}
    assert TimeConfiguration.model_validate(body).grid_slot_mapping == {"1": 2, "2": 2}
    for mapping in ({"1": 3}, {"01": 1}, {"1": 2, "2": 1}, {"61": 1}):
        with pytest.raises(ValueError):
            TimeConfiguration.model_validate({**body, "grid_slot_mapping": mapping})


@pytest.mark.parametrize(
    "periods",
    [
        [
            {"period_no": 1, "start_time": "07:00", "end_time": "07:40"},
            {"period_no": 1, "start_time": "08:00", "end_time": "08:40"},
        ],
        [
            {"period_no": 1, "start_time": "07:00", "end_time": "08:10"},
            {"period_no": 2, "start_time": "08:00", "end_time": "08:40"},
        ],
        [
            {"period_no": 1, "start_time": "08:00", "end_time": "08:40"},
            {"period_no": 2, "start_time": "07:00", "end_time": "07:40"},
        ],
        [{"period_no": 1, "start_time": "07:00:01", "end_time": "07:40"}],
        [{"period_no": 1, "start_time": "07:00+08:00", "end_time": "07:40"}],
    ],
)
def test_time_configuration_rejects_invalid_period_inputs(periods):
    body = configuration()
    body["periods"] = periods
    with pytest.raises(ValueError):
        TimeConfiguration.model_validate(body)


def test_time_configuration_rejects_duplicate_calendar_date():
    body = configuration()
    body["calendar"] = [
        {"date": "2026-09-08", "override_type": "STOP"},
        {"date": "2026-09-08", "override_type": "STOP"},
    ]
    with pytest.raises(ValueError, match="同日"):
        TimeConfiguration.model_validate(body)


def test_time_configuration_requires_makeup_source_weekday():
    body = configuration()
    body["calendar"] = [{"date": "2026-09-08", "override_type": "MAKEUP"}]
    with pytest.raises(ValueError, match="来源星期"):
        TimeConfiguration.model_validate(body)


def test_time_configuration_rejects_stop_with_makeup_source():
    body = configuration()
    body["calendar"] = [
        {
            "date": "2026-09-08",
            "override_type": "STOP",
            "source_teaching_weekday": 2,
        }
    ]
    with pytest.raises(ValueError, match="停课"):
        TimeConfiguration.model_validate(body)


def test_preview_rejects_effective_and_calendar_dates_outside_teaching_class_semester(campus):
    from app.modules.academic.models import Semester
    from app.modules.academic.time_service import CollegeTimeService

    _, db, admin, _, a, b = campus
    one, two, unknown, teaching, *_ = records(db, a, b)
    # The semester belongs to the TeachingClass. AdministrativeClass has no semester_id.
    semester = db.get(Semester, teaching.semester_id)
    assert semester.start_date == date(2026, 9, 1)
    service = CollegeTimeService(db, admin, int(a["id"]), semester.id)
    with pytest.raises(AppError, match="生效日期"):
        service.preview(configuration(day="2026-08-31"))
    body = configuration()
    body["calendar"] = [{"date": "2027-02-01", "override_type": "STOP"}]
    with pytest.raises(AppError, match="校历日期"):
        service.preview(body)


def test_preview_rejects_unknown_semester(campus):
    from app.modules.academic.time_service import CollegeTimeService

    _, db, admin, _, a, _ = campus
    with pytest.raises(NotFoundError):
        CollegeTimeService(db, admin, int(a["id"]), 987654321).preview(configuration())


def test_future_tasks_are_reported_and_publish_requires_confirmation(campus, monkeypatch):
    from app.modules.academic.models import Semester
    from app.modules.academic.time_service import CollegeTimeService

    _, db, admin, _, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    semester = db.get(Semester, teaching.semester_id)
    service = CollegeTimeService(db, admin, int(a["id"]), semester.id)
    task = db.query(InspectionTask).one()
    # The seeded task is historical relative to business_today; move it into the simulated future.
    task.college_id = int(a["id"])
    task.inspection_date = date(2026, 9, 9)
    task.start_period, task.end_period, task.week_no = 3, 4, 2
    db.commit()
    monkeypatch.setattr(
        "app.modules.academic.time_service.business_today", lambda: date(2026, 9, 7)
    )
    body = configuration(day="2026-09-08")
    preview = service.preview(body)
    assert preview["retained_future_task_ids"] == [str(task.id)]
    assert preview["existing_tasks_keep_snapshot"] is True
    with pytest.raises(ConflictError, match="请确认影响"):
        service.publish(body, preview["revision"])
    task_before = (task.inspection_date, task.start_period, task.end_period, task.week_no)
    confirmed = {**body, "confirm_existing_tasks": True}
    result = service.publish(confirmed, service.preview(confirmed)["revision"])
    assert result["retained_future_task_ids"] == [str(task.id)]
    db.refresh(task)
    assert (task.inspection_date, task.start_period, task.end_period, task.week_no) == task_before
