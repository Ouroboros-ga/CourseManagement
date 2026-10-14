from datetime import datetime

import pytest
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask, SubmissionDeadlineDay
from app.modules.inspection.schemas import DeadlineDayUpdateRequest
from app.modules.inspection.scoped_service import ScopedInspectionService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_new_tasks_bind_college_deadline_and_updates_do_not_touch_another_college(
    campus, monkeypatch
):
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    day = datetime(2026, 9, 7, 14)
    old = SubmissionDeadlineDay(
        semester_id=sem.id,
        inspection_date=day.date(),
        ownership_scope_id=0,
        deadline_at=day,
        version=1,
    )
    other = SubmissionDeadlineDay(
        semester_id=sem.id,
        inspection_date=day.date(),
        ownership_scope_id=int(campus[5]["id"]),
        deadline_at=day,
        version=1,
    )
    db.add_all([old, other])
    db.commit()
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "deadline",
    }
    generated = sampling.generate(body, sampling.preview(body)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    own_day = db.get(SubmissionDeadlineDay, task.deadline_day_id)
    assert own_day.ownership_scope_id == int(a["id"])
    service = ScopedInspectionService(db, admin, int(a["id"]))
    listed = service.list_deadline_days(admin, semester_id=sem.id, date_from=None, date_to=None)
    assert len(listed) == 1 and listed[0].task_count == 1
    service.update_deadline_day(
        admin,
        sem.id,
        day.date(),
        DeadlineDayUpdateRequest(time="21:30", lock_version=own_day.version),
        None,
    )
    db.expire_all()
    assert db.get(SubmissionDeadlineDay, other.id).deadline_at == day
    assert db.get(SubmissionDeadlineDay, old.id).deadline_at == day
    assert db.get(SubmissionDeadlineDay, own_day.id).deadline_at == datetime(2026, 9, 7, 13, 30)
    legacy = InspectionTask(
        task_key="legacy-school-deadline",
        semester_id=sem.id,
        college_id=int(a["id"]),
        inspection_date=day.date(),
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=1,
    )
    db.add(legacy)
    db.commit()
    assert service._repo.deadline_for_task(legacy).id == old.id


def test_new_late_evening_tasks_seed_cutoff_after_actual_end(campus, monkeypatch):
    from app.modules.academic.time_service import CollegeTimeService

    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    times = CollegeTimeService(db, admin, int(a["id"]), sem.id)
    config = {
        "effective_from": "2026-09-01",
        "periods": [
            {"period_no": 1, "start_time": "22:30", "end_time": "23:00"},
            {"period_no": 2, "start_time": "23:10", "end_time": "23:30"},
        ],
    }
    times.publish(config, times.preview(config)["revision"])
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "late",
    }
    generated = sampling.generate(body, sampling.preview(body)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    deadline = db.get(SubmissionDeadlineDay, task.deadline_day_id)
    assert deadline.deadline_at == datetime(2026, 9, 7, 15, 59)
    assert deadline.deadline_at >= task.activity_end_at
