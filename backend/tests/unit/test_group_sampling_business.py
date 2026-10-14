import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.academic.models import CourseScheduleWeek, PeriodDefinition, TeachingClassStudent
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def arrange(campus, monkeypatch):
    from datetime import time

    from app.modules.academic.models import CourseSchedule, TeachingClass
    from app.modules.academic.scoped_service import ScopedAcademicService

    config, db, admin, a, b, sem, group, _, own, foreign = prepare(campus)
    teaching = db.scalar(select(TeachingClass))
    schedule = db.scalar(select(CourseSchedule))
    kind = config.create_type(admin, int(a["id"]), {"name": "早查"})
    other = config.create_type(admin, int(a["id"]), {"name": "常规"})
    ScopedAcademicService(db, admin, int(a["id"])).set_course_type(teaching.id, int(kind["id"]), 1)
    db.add_all(
        [
            TeachingClassStudent(teaching_class_id=teaching.id, student_id=own.id),
            CourseScheduleWeek(schedule_id=schedule.id, week_no=2),
            PeriodDefinition(
                semester_id=sem.id, period_no=1, start_time=time(7), end_time=time(7, 40)
            ),
            PeriodDefinition(
                semester_id=sem.id, period_no=2, start_time=time(7, 50), end_time=time(8, 30)
            ),
        ]
    )
    db.commit()
    group = config.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"lock_version": group["lock_version"], "course_type_ids": [kind["id"]]},
    )
    config.update_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"lock_version": group["lock_version"], "status": "ACTIVE"},
    )
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    return db, admin, a, sem, group, own, teaching, other


def test_group_preview_prefetches_time_versions_instead_of_querying_each_day(campus, monkeypatch):
    from app.modules.inspection.group_sampling import GroupSamplingService
    from sqlalchemy import event

    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    statements = []

    def count(*args):
        if "from college_time_version" in args[2].lower():
            statements.append(args[2])

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        service = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
        service.preview(
            {
                "semester_id": str(sem.id),
                "date_from": "2026-09-07",
                "date_to": "2026-09-13",
                "counts": {str(own.administrative_class_id): 1},
                "draw_id": "prefetch",
            }
        )
        assert len(statements) <= 4
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)


def test_group_generation_preserves_scope_config_type_and_real_time(campus, monkeypatch):
    from app.modules.inspection.group_sampling import GroupSamplingService
    from app.modules.inspection.models import InspectionTask
    from app.modules.inspection.task_time import task_minutes

    db, admin, a, sem, group, own, teaching, _ = arrange(campus, monkeypatch)
    service = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "one",
    }
    preview = service.preview(body)
    assert preview["selected_count"] == 1
    result = service.generate(body, preview["selection_revision"])
    assert result.created == 1
    task = db.scalar(select(InspectionTask).where(InspectionTask.group_id == int(group["id"])))
    assert task.college_id == int(a["id"])
    assert task.course_type_id_snapshot == teaching.course_type_id
    assert task.group_config_version_id and task.group_name_snapshot
    assert task_minutes(task) == (420, 510)
    assert service.generate(body, service.preview(body)["selection_revision"]).created == 0


def test_reclassification_invalidates_group_preview_and_never_fills_other_type(campus, monkeypatch):
    from app.modules.academic.scoped_service import ScopedAcademicService
    from app.modules.inspection.group_sampling import GroupSamplingService

    db, admin, a, sem, group, own, teaching, other = arrange(campus, monkeypatch)
    service = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "one",
    }
    preview = service.preview(body)
    ScopedAcademicService(db, admin, int(a["id"])).set_course_type(teaching.id, int(other["id"]), 2)
    with pytest.raises(ConflictError):
        service.generate(body, preview["selection_revision"])
