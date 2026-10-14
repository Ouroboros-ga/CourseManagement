from datetime import datetime

import pytest
from app.modules.academic.models import PeriodDefinition
from app.modules.academic.time_service import CollegeTimeService
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import TaskCancelRequest
from app.modules.inspection.scoped_service import ScopedInspectionService
from sqlalchemy import delete

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_restore_group_task_uses_frozen_time_without_school_period_definitions(campus, monkeypatch):
    import app.modules.inspection.restore_service as module

    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    times = CollegeTimeService(db, admin, int(a["id"]), sem.id)
    config = {
        "effective_from": "2026-09-01",
        "periods": [
            {"period_no": 1, "start_time": "07:00", "end_time": "07:40"},
            {"period_no": 2, "start_time": "07:50", "end_time": "08:30"},
        ],
    }
    times.publish(config, times.preview(config)["revision"])
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "restore",
    }
    generated = sampling.generate(body, sampling.preview(body)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    task.canceled_at = datetime(2026, 9, 6)
    db.execute(delete(PeriodDefinition))
    db.commit()
    monkeypatch.setattr(module, "utcnow", lambda: datetime(2026, 9, 6))
    result = module.restore_task(
        ScopedInspectionService(db, admin, int(a["id"])),
        admin,
        task.id,
        TaskCancelRequest(lock_version=task.lock_version),
        None,
    )
    assert result.canceled_at is None
    assert result.activity_start_at.hour == 23
    assert result.group_id == group["id"]
