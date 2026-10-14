from datetime import date

import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.academic.time_service import CollegeTimeService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.schemas import InspectionTaskUpdateRequest
from app.modules.inspection.service import InspectionService
from app.modules.inspection.task_time import freeze_time, task_minutes
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_college_time import configuration
from tests.unit.test_scoped_file_access import setup
from tests.unit.test_scoped_inspection_management import grant_global_permission


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_task_edit_accepts_configured_periods_above_legacy_twenty(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    assert InspectionTaskUpdateRequest(start_period=21, end_period=23).end_period == 23
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", False)
    with pytest.raises(ValidationError):
        InspectionTaskUpdateRequest(start_period=21, end_period=23)


def prepare(campus, monkeypatch):
    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    grant_global_permission(db, "inspection.generate")
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    task = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[4]["id"]))
    )
    task = InspectionTask(
        task_key="unsubmitted-edit",
        college_id=task.college_id,
        semester_id=task.semester_id,
        inspection_date=date(2026, 9, 7),
        week_no=1,
        inspection_type="COURSE",
        start_period=1,
        end_period=1,
    )
    db.add(task)
    db.flush()
    service = CollegeTimeService(db, campus[2], task.college_id, task.semester_id)
    body = configuration()
    body["periods"].append({"period_no": 2, "start_time": "08:00", "end_time": "08:40"})
    service.publish(body, service.preview(body)["revision"])
    freeze_time(db, task)
    db.commit()
    return actor, db, task


def test_schedule_edit_refreshes_actual_time_and_checks_version(campus, monkeypatch):
    actor, db, task = prepare(campus, monkeypatch)
    service = InspectionService(db)
    before = task.lock_version
    service.update_task_schedule_info(
        actor,
        task.id,
        InspectionTaskUpdateRequest(start_period=2, end_period=2, lock_version=before),
        None,
    )
    assert task_minutes(task) == (480, 520)
    with pytest.raises(ConflictError):
        service.update_task_schedule_info(
            actor,
            task.id,
            InspectionTaskUpdateRequest(classroom="stale", lock_version=before),
            None,
        )


def test_scheduling_mode_cannot_edit_periods_of_assigned_task(campus, monkeypatch):
    actor, db, task = prepare(campus, monkeypatch)
    db.add(
        InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=campus[2].id,
            assign_method="MANUAL",
            assigned_by=campus[2].id,
        )
    )
    db.commit()
    previous = task_minutes(task)
    with pytest.raises(ConflictError):
        InspectionService(db).update_task_schedule_info(
            actor,
            task.id,
            InspectionTaskUpdateRequest(
                start_period=2, end_period=2, lock_version=task.lock_version
            ),
            None,
        )
    assert task_minutes(task) == previous


def test_group_weekly_caps_lock_whole_week_even_without_global_week_cap(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(get_settings(), "assignment_max_tasks_per_week", 0)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    service = InspectionService.__new__(InspectionService)
    service._repo = Mock()
    service._lock_day_anchors({(123, date(2026, 9, 9))})
    assert service._repo.lock_volunteer_day.call_count == 7


def test_manual_group_task_must_match_frozen_specific_class_scope(campus):
    from app.modules.volunteer.models import GroupConfigVersion
    from app.modules.volunteer.rules import GroupRules

    from tests.unit.test_group_rules import prepared_task

    db, task, own, *_ = prepared_task(campus)
    version = db.get(GroupConfigVersion, task.group_config_version_id)
    version.configuration = {
        **version.configuration,
        "class_mode": "SPECIFIC",
        "class_ids": [str(own.administrative_class_id)],
    }
    db.commit()
    task.administrative_class_id = 999
    with pytest.raises(ConflictError):
        GroupRules(db, task)
