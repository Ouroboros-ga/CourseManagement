from datetime import timedelta

import pytest
from app.core.exceptions import ConflictError
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_merged_task_impact_includes_nonrepresentative_teaching_class(campus):
    from app.modules.academic.models import CourseSchedule, TeachingClass
    from app.modules.inspection.models import TaskScheduleSource
    from app.modules.organization.future_impact import future_impact

    _, db, _, a, _, _, _, *_ = prepare(campus)
    first = db.scalar(select(TeachingClass))
    extra = TeachingClass(
        semester_id=first.semester_id,
        course_id=first.course_id,
        college_id=int(a["id"]),
        class_code="MERGED-OTHER",
        class_name="合班另一来源",
    )
    db.add(extra)
    db.flush()
    schedule = CourseSchedule(
        semester_id=first.semester_id,
        teaching_class_id=extra.id,
        college_id=int(a["id"]),
        weekday=1,
        start_period=1,
        end_period=2,
    )
    db.add(schedule)
    db.flush()
    task = db.scalar(select(InspectionTask))
    task.inspection_date = business_today() + timedelta(days=1)
    db.add(
        TaskScheduleSource(
            task_id=task.id, course_schedule_id=schedule.id, teaching_class_id=extra.id
        )
    )
    db.commit()
    impact = future_impact(
        db, int(a["id"]), "teaching_class", extra.id, extra.classification_revision
    )
    assert impact["retained_future_task_ids"] == [str(task.id)]


def test_type_and_group_changes_require_current_impact_and_preserve_existing_tasks(campus):
    config, db, actor, a, _, _, group, *_ = prepare(campus)
    kind = config.create_type(actor, int(a["id"]), {"name": "Morning"})
    task = db.scalar(select(InspectionTask))
    task.group_id = int(group["id"])
    task.course_type_id_snapshot = int(kind["id"])
    task.inspection_date = business_today() + timedelta(days=1)
    frozen_name = task.course_name_snapshot
    db.commit()
    for resource, row, method in (
        ("course_type", kind, config.update_type),
        ("group", group, config.update_group),
    ):
        body = {"lock_version": row["lock_version"], "status": "INACTIVE"}
        with pytest.raises(ConflictError):
            method(actor, int(a["id"]), int(row["id"]), body)
        old = config.configuration_impact(actor, int(a["id"]), resource, int(row["id"]))
        task = db.get(InspectionTask, task.id)
        task.lock_version += 1
        db.commit()
        with pytest.raises(ConflictError):
            method(
                actor,
                int(a["id"]),
                int(row["id"]),
                {**body, "future_impact_revision": old["revision"]},
            )
        current = config.configuration_impact(actor, int(a["id"]), resource, int(row["id"]))
        assert current["retained_future_task_ids"] == [str(task.id)]
        method(
            actor,
            int(a["id"]),
            int(row["id"]),
            {**body, "future_impact_revision": current["revision"]},
        )
        retained = db.get(InspectionTask, task.id, populate_existing=True)
        assert retained.course_name_snapshot == frozen_name and retained.canceled_at is None
