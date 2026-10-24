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
    from datetime import date

    from app.modules.inspection.models import InspectionTask
    # The ownership fixture also seeds a legacy task. Keep it on another occurrence;
    # a different task key must never authorize duplicate generation for the same day.
    db.scalar(select(InspectionTask)).inspection_date = date(2026, 9, 8)
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


def test_generation_can_share_callers_transaction_and_roll_back_all_business_facts(
    campus, monkeypatch
):
    from app.modules.audit.models import AuditLog
    from app.modules.inspection.group_sampling import GroupSamplingService
    from app.modules.inspection.models import (
        InspectionTask,
        TaskRosterMember,
        SubmissionDeadlineDay,
        SubmissionDeadlineVersion,
    )

    db, admin, college, semester, group, own, _, _ = arrange(campus, monkeypatch)
    service = GroupSamplingService(db, admin, int(college["id"]), int(group["id"]))
    body = {
        "semester_id": str(semester.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "weekly-transaction",
    }
    models = [
        InspectionTask,
        TaskRosterMember,
        SubmissionDeadlineDay,
        SubmissionDeadlineVersion,
        AuditLog,
    ]
    before = [db.query(model).count() for model in models]
    revision = service.preview(body)["selection_revision"]
    result = service.generate_in_transaction(body, revision)
    assert result.created == 1
    assert db.query(InspectionTask).count() == before[0] + 1
    db.rollback()
    assert [db.query(model).count() for model in models] == before


def test_explicit_course_type_filter_is_exact_and_cannot_expand_group_scope(campus, monkeypatch):
    from app.modules.inspection.group_sampling import GroupSamplingService
    from app.core.exceptions import NotFoundError

    db, admin, college, semester, group, own, teaching, other = arrange(campus, monkeypatch)
    service = GroupSamplingService(db, admin, int(college["id"]), int(group["id"]))
    body = {
        "semester_id": str(semester.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "explicit-types",
        "course_type_ids": [str(teaching.course_type_id)],
    }
    assert service.preview(body)["selected_count"] == 1
    with pytest.raises(NotFoundError):
        service.preview({**body, "course_type_ids": [other["id"]]})
    from app.modules.academic.scoped_service import ScopedAcademicService
    from app.modules.organization.service import CampusService
    from app.modules.volunteer.models import VolunteerGroup

    current = db.get(VolunteerGroup, int(group["id"]))
    CampusService(db).publish_group(
        admin,
        int(college["id"]),
        current.id,
        {
            "lock_version": current.lock_version,
            "course_type_ids": [str(teaching.course_type_id), other["id"]],
        },
    )
    ScopedAcademicService(db, admin, int(college["id"])).set_course_type(
        teaching.id, int(other["id"]), teaching.classification_revision
    )
    with pytest.raises(ConflictError):
        service.preview(body)
    assert service.preview({**body, "course_type_ids": [other["id"]]})["selected_count"] == 1
    from app.modules.academic.campus_models import CourseType

    db.get(CourseType, int(body["course_type_ids"][0])).status = "INACTIVE"
    db.commit()
    with pytest.raises(NotFoundError):
        service.preview(body)
    # An omitted filter preserves the original group-wide behavior: inactive
    # types are skipped rather than blocking unrelated active types.
    assert (
        service.preview({key: value for key, value in body.items() if key != "course_type_ids"})[
            "selected_count"
        ]
        == 1
    )


@pytest.mark.parametrize("ids", [[], ["01"], [True], ["1", "1"], [str(2**63)]])
def test_explicit_type_filter_refuses_ambiguous_identifiers(ids):
    from app.modules.inspection.group_sampling import GroupSampleRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GroupSampleRequest.model_validate(
            {
                "semester_id": "1",
                "date_from": "2026-09-07",
                "date_to": "2026-09-07",
                "counts": {"1": 1},
                "draw_id": "strict",
                "course_type_ids": ids,
            }
        )
