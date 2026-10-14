"""归属回填须明确确认、绑定预览版本并原子传播，不猜测教学班所属学院。"""

from datetime import date

import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    Semester,
    TeachingClass,
)
from app.modules.audit.models import AuditLog
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def ownership_fixture():
    yield from campus_fixture.__wrapped__()


def legacy(db):
    semester = Semester(
        code="OLD",
        name="旧学期",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 30),
        first_monday=date(2026, 8, 31),
    )
    course = Course(course_code="OLD", course_name="旧课程")
    admin_class = AdministrativeClass(class_code="A1", class_name="一班", college="甲院")
    db.add_all([semester, course, admin_class])
    db.flush()
    teaching = TeachingClass(semester_id=semester.id, course_id=course.id, class_name="教学一班")
    db.add(teaching)
    db.flush()
    schedule = CourseSchedule(
        semester_id=semester.id,
        teaching_class_id=teaching.id,
        weekday=1,
        start_period=1,
        end_period=2,
    )
    db.add(schedule)
    db.flush()
    task = InspectionTask(
        task_key="OLD",
        semester_id=semester.id,
        inspection_date=date(2026, 9, 7),
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        course_schedule_id=schedule.id,
        teaching_class_id=teaching.id,
    )
    db.add(task)
    db.commit()
    return admin_class, teaching, schedule, task


def ownership(db):
    from app.modules.organization.ownership import OwnershipService

    return OwnershipService(db)


def test_preview_never_guesses_from_legacy_college_text(campus):
    _, db, actor, _, a, _ = campus
    admin_class, teaching, schedule, task = legacy(db)
    preview = ownership(db).preview(actor, {})
    assert preview["changes"] == []
    assert preview["unresolved"]["administrative_class"] == 1
    assert db.get(AdministrativeClass, admin_class.id).college_id is None
    assert all(row.college_id is None for row in (teaching, schedule, task))


def test_explicit_teaching_owner_propagates_schedule_and_task_atomically(campus):
    _, db, actor, _, a, _ = campus
    _, teaching, schedule, task = legacy(db)
    service = ownership(db)
    mapping = {"teaching_class": {str(teaching.id): a["id"]}}
    preview = service.preview(actor, mapping)
    assert len(preview["changes"]) == 3
    result = service.apply(actor, mapping, preview["revision"])
    assert result["updated"] == 3
    assert all(row.college_id == int(a["id"]) for row in (teaching, schedule, task))
    assert db.scalar(select(AuditLog).where(AuditLog.action == "campus.ownership.backfill"))
    assert service.preview(actor, mapping)["changes"] == []


def test_conflicting_parent_chains_refuse_whole_batch(campus):
    _, db, actor, _, a, b = campus
    admin_class, teaching, _, task = legacy(db)
    task.administrative_class_id = admin_class.id
    db.commit()
    service = ownership(db)
    mapping = {
        "administrative_class": {str(admin_class.id): b["id"]},
        "teaching_class": {str(teaching.id): a["id"]},
    }
    preview = service.preview(actor, mapping)
    assert preview["conflicts"]
    with pytest.raises(ConflictError):
        service.apply(actor, mapping, preview["revision"])
    db.refresh(teaching)
    assert teaching.college_id is None


def test_preview_stales_when_parent_or_root_changes(campus):
    _, db, actor, _, a, _ = campus
    _, teaching, _, task = legacy(db)
    service = ownership(db)
    mapping = {"teaching_class": {str(teaching.id): a["id"]}}
    preview = service.preview(actor, mapping)
    task.teaching_class_id = None
    db.commit()
    with pytest.raises(ConflictError):
        service.apply(actor, mapping, preview["revision"])
    assert teaching.college_id is None


def test_known_ownership_cannot_be_transferred_by_backfill(campus):
    _, db, actor, _, a, b = campus
    _, teaching, _, _ = legacy(db)
    service = ownership(db)
    mapping = {"teaching_class": {str(teaching.id): a["id"]}}
    service.apply(actor, mapping, service.preview(actor, mapping)["revision"])
    bad = {"teaching_class": {str(teaching.id): b["id"]}}
    preview = service.preview(actor, bad)
    assert preview["conflicts"]
    with pytest.raises(ConflictError):
        service.apply(actor, bad, preview["revision"])


def test_forged_super_role_cannot_preview_or_apply(campus):
    _, db, _, teacher, _, _ = campus
    with pytest.raises(PermissionDeniedError):
        ownership(db).preview(teacher, {})
