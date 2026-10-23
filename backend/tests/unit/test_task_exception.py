from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from app.core.exceptions import AppError
from app.modules.academic.models import VolunteerQualification
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.seed import sync_registry
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.schemas import SubmissionCreateRequest, TaskCancelRequest
from app.modules.inspection.scoped_service import ScopedInspectionService
from app.modules.inspection.service import InspectionService
from app.modules.report.source_revision import SourceRevisionService
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


@pytest.fixture
def execution(campus, monkeypatch):
    db, admin, college, sem, group, own, *_ = arrange(campus, monkeypatch)
    sync_registry(db)
    user = UserAccount(display_name="志愿者甲", student_id=own.id, status="ACTIVE")
    db.add(user)
    db.flush()
    for code in ("STUDENT", "VOLUNTEER"):
        db.add(
            UserRole(user_id=user.id, role_id=db.scalar(select(Role.id).where(Role.code == code)))
        )
    db.add(
        VolunteerQualification(
            student_id=own.id, semester_id=sem.id, college_id=int(college["id"]), enabled=True
        )
    )
    task = InspectionTask(
        task_key="exception-test",
        semester_id=sem.id,
        college_id=int(college["id"]),
        inspection_date=datetime(2026, 9, 7).date(),
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
    )
    db.add(task)
    db.flush()
    db.add(
        InspectionAssignment(
            task_id=task.id, volunteer_user_id=user.id, assign_method="MANUAL", assigned_by=admin.id
        )
    )
    db.commit()
    if db.get_bind().dialect.name != "mysql":
        monkeypatch.setattr(SourceRevisionService, "bump_for_task", lambda *_: None)
    actor = replace(
        admin, id=user.id, roles=["STUDENT", "VOLUNTEER"], permissions=["submission.create"]
    )
    return db, admin, actor, college, task


def test_exception_effective_immediately_without_attendance_and_can_restore(execution):
    db, admin, actor, college, task = execution
    service = InspectionService(db)
    result = service.report_exception(
        actor, task.id, TaskCancelRequest(lock_version=0, reason="临时换教室"), None
    )
    assert result.status == "异常"
    assert result.exception_reporter_name == "志愿者甲"
    assert result.exception_reason == "临时换教室"
    assert result.assignment.volunteer_user_id == str(actor.id)
    assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 0
    with pytest.raises(AppError):
        service.create_submission(actor, task.id, SubmissionCreateRequest(result="NORMAL"), None)
    restored = ScopedInspectionService(db, admin, int(college["id"])).clear_exception(
        admin, task.id, TaskCancelRequest(lock_version=1), None
    )
    assert restored.status != "异常"
    assert restored.exception_reported_at is None
    assert restored.lock_version == 2


def test_exception_rejects_non_assignee_stale_version_and_future(execution):
    db, admin, actor, college, task = execution
    service = InspectionService(db)
    with pytest.raises(AppError):
        service.report_exception(
            replace(actor, id=admin.id), task.id, TaskCancelRequest(lock_version=0), None
        )
    with pytest.raises(AppError):
        service.report_exception(actor, task.id, TaskCancelRequest(lock_version=9), None)
    task = db.get(InspectionTask, task.id)
    task.inspection_date = (datetime.now() + timedelta(days=10)).date()
    db.commit()
    with pytest.raises(AppError):
        service.report_exception(actor, task.id, TaskCancelRequest(lock_version=0), None)


def test_exception_status_sql_and_report_denominator(execution):
    from app.modules.inspection.list_queries import task_status_expression
    from app.modules.report.summary_router import aggregate

    db, admin, actor, college, task = execution
    InspectionService(db).report_exception(actor, task.id, TaskCancelRequest(lock_version=0), None)
    assert (
        db.scalar(select(task_status_expression()).where(InspectionTask.id == task.id))
        == "EXCEPTION"
    )
    row = aggregate(db, task.semester_id, [InspectionTask.id == task.id])[0]
    assert row["exception_count"] == 1
    assert row["task_count"] == 0
    assert row["incomplete_count"] == 0


def test_exception_does_not_replace_existing_submission(execution):
    from app.modules.inspection.models import InspectionSubmission

    db, admin, actor, college, task = execution
    db.add(
        InspectionSubmission(
            task_id=task.id,
            volunteer_user_id=actor.id,
            result="NORMAL",
            review_status="APPROVED",
            submitted_at=datetime(2026, 9, 7),
            attempt_no=1,
            roster_version=1,
        )
    )
    db.commit()
    with pytest.raises(AppError):
        InspectionService(db).report_exception(
            actor, task.id, TaskCancelRequest(lock_version=0), None
        )
    assert db.get(InspectionTask, task.id).exception_reported_at is None


def test_exception_deadline_snapshot_and_restore_preserve_history(execution, monkeypatch):
    from app.modules.inspection.models import SubmissionDeadlineDay, TaskDeadlineAssessment

    db, admin, actor, college, task = execution
    day = SubmissionDeadlineDay(
        semester_id=task.semester_id,
        inspection_date=task.inspection_date,
        ownership_scope_id=0,
        deadline_at=datetime(2026, 9, 7, 14),
        version=1,
    )
    db.add(day)
    db.flush()
    task.deadline_day_id = day.id
    db.commit()
    monkeypatch.setattr("app.modules.inspection.service.utcnow", lambda: datetime(2026, 9, 7, 12))
    monkeypatch.setattr(
        "app.modules.inspection.exception_service.utcnow", lambda: datetime(2026, 9, 7, 12)
    )
    service = InspectionService(db)
    service.report_exception(actor, task.id, TaskCancelRequest(lock_version=0), None)
    monkeypatch.setattr("app.modules.inspection.service.utcnow", lambda: datetime(2026, 9, 7, 15))
    assessment, outcome = service._settle_assessment(task, day)
    assert assessment.result == "EXCEPTION"
    db.commit()
    restored = ScopedInspectionService(db, admin, int(college["id"])).clear_exception(
        admin, task.id, TaskCancelRequest(lock_version=1), None
    )
    assert restored.status == "已逾期"
    assert (
        db.scalar(
            select(TaskDeadlineAssessment.result).where(TaskDeadlineAssessment.task_id == task.id)
        )
        == "EXCEPTION"
    )


def test_late_exception_keeps_overdue_snapshot_but_excludes_current_incomplete(execution):
    from app.modules.inspection.models import SubmissionDeadlineDay, TaskDeadlineAssessment
    from app.modules.report.repository import ReportRepository

    db, admin, actor, college, task = execution
    day = SubmissionDeadlineDay(
        semester_id=task.semester_id,
        inspection_date=task.inspection_date,
        ownership_scope_id=0,
        deadline_at=datetime(2026, 9, 7, 14),
        version=1,
    )
    db.add(day)
    db.flush()
    task.deadline_day_id = day.id
    db.commit()
    InspectionService(db).report_exception(actor, task.id, TaskCancelRequest(lock_version=0), None)
    assert (
        db.scalar(
            select(TaskDeadlineAssessment.result).where(TaskDeadlineAssessment.task_id == task.id)
        )
        == "OVERDUE_UNEXECUTED"
    )
    repo = ReportRepository(db)
    ids = repo._task_ids_subq(semester_id=task.semester_id, week_no=2, date_from=None, date_to=None)
    assert task.id not in set(db.scalars(ids))


def test_other_college_cannot_clear_exception(execution, campus):
    db, admin, actor, college, task = execution
    InspectionService(db).report_exception(actor, task.id, TaskCancelRequest(lock_version=0), None)
    with pytest.raises(AppError):
        ScopedInspectionService(db, admin, int(campus[5]["id"])).clear_exception(
            admin, task.id, TaskCancelRequest(lock_version=1), None
        )
    assert db.get(InspectionTask, task.id).exception_reported_at is not None


def test_exception_rechecks_qualification_and_archived_semester(execution):
    from app.modules.academic.models import Semester

    db, admin, actor, college, task = execution
    qualification = db.scalar(
        select(VolunteerQualification).where(
            VolunteerQualification.semester_id == task.semester_id,
            VolunteerQualification.student_id == db.get(UserAccount, actor.id).student_id,
        )
    )
    qualification.enabled = False
    db.commit()
    with pytest.raises(AppError):
        InspectionService(db).report_exception(
            actor, task.id, TaskCancelRequest(lock_version=0), None
        )
    qualification.enabled = True
    db.get(Semester, task.semester_id).status = "ARCHIVED"
    db.commit()
    with pytest.raises(AppError):
        InspectionService(db).report_exception(
            actor, task.id, TaskCancelRequest(lock_version=0), None
        )
    assert db.get(InspectionTask, task.id).exception_reported_at is None


def test_second_valid_volunteer_cannot_report_another_assignees_task(execution):
    db, admin, actor, college, task = execution
    other = UserAccount(display_name="另一志愿者", status="ACTIVE")
    db.add(other)
    db.flush()
    db.add(
        UserRole(
            user_id=other.id, role_id=db.scalar(select(Role.id).where(Role.code == "VOLUNTEER"))
        )
    )
    db.commit()
    with pytest.raises(AppError):
        InspectionService(db).report_exception(
            replace(actor, id=other.id), task.id, TaskCancelRequest(lock_version=0), None
        )
    assert db.get(InspectionTask, task.id).exception_reported_at is None
