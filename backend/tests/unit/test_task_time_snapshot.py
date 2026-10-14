from datetime import date

import pytest
from app.core.exceptions import ConflictError
from app.modules.inspection.models import InspectionTask

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_college_time import configuration
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_task_time_is_frozen_and_not_recomputed_from_changed_configuration(campus):
    from app.modules.academic.time_service import CollegeTimeService
    from app.modules.inspection.task_time import freeze_time, task_minutes
    from sqlalchemy import select

    _, db, admin, _, a, b = campus
    _, _, _, teaching, *_ = records(db, a, b)
    task = db.scalar(select(InspectionTask).where(InspectionTask.college_id == int(a["id"])))
    service = CollegeTimeService(db, admin, int(a["id"]), teaching.semester_id)
    body = configuration()
    body["periods"].append({"period_no": 2, "start_time": "07:50", "end_time": "08:30"})
    service.publish(body, service.preview(body)["revision"])
    freeze_time(db, task)
    db.commit()
    assert task_minutes(task) == (420, 510)
    body["periods"] = [
        {"period_no": 1, "start_time": "09:00", "end_time": "09:40"},
        {"period_no": 2, "start_time": "09:50", "end_time": "10:30"},
    ]
    service.publish(body, service.preview(body)["revision"])
    assert task_minutes(task) == (420, 510)


def test_unknown_historical_time_cannot_use_current_clock():
    from app.modules.inspection.task_time import task_minutes

    task = InspectionTask(inspection_date=date(2026, 9, 7), start_period=1, end_period=2)
    with pytest.raises(ConflictError):
        task_minutes(task)
