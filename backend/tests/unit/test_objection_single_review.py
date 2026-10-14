"""一次异议审核的事务与权限回归；SQLite 不证明 MySQL 锁语义。"""

from datetime import date, datetime

import pytest
from app.core.database import Base
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.enrollment_models import (
    StudentEnrollment,
    StudentManagerAppointment,
    TeacherCollegeBinding,
)
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.attendance.models import AttendanceRecord, AttendanceRecordVersion
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount
from app.modules.identity.policy import MANAGER_FUNCTION_CODES
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from app.modules.objection.models import Objection
from app.modules.objection.schemas import ObjectionFinalReviewRequest, ObjectionInitialReviewRequest
from app.modules.objection.service import ObjectionService
from app.modules.organization.models import College, School
from app.modules.report.source_revision import SourceRevisionService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def setup_review(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sync_registry(db)
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add(College(id=1, school_id=1, code="C", name="学院"))
        db.flush()
        db.add(AdministrativeClass(id=1, class_code="C1", class_name="班级", college_id=1))
        db.flush()
        db.add(
            Student(id=2, student_no="reviewer_student", name="负责人", administrative_class_id=1)
        )
        db.flush()
        db.add(
            StudentEnrollment(
                student_id=2,
                administrative_class_id=1,
                college_id=1,
                effective_from=date(2020, 1, 1),
                status="ENROLLED",
                revision=0,
                historical_confirmed=True,
                snapshot={"class_name": "班级"},
            )
        )
        manager = UserAccount(
            id=1, username="reviewer", display_name="学生负责人", status="ACTIVE", student_id=2
        )
        manager.roles = [db.scalar(select(Role).where(Role.code == "STUDENT_AFFAIRS_MANAGER"))]
        db.add(manager)
        db.flush()
        db.add(
            StudentManagerAppointment(
                user_id=1,
                college_id=1,
                effective_from=date(2020, 1, 1),
                allowed_actions=sorted(MANAGER_FUNCTION_CODES),
            )
        )
        db.add(TeacherCollegeBinding(user_id=1, college_id=1))
        db.add(
            InspectionTask(
                id=1,
                college_id=1,
                task_key="review",
                semester_id=1,
                inspection_date=date(2026, 1, 1),
                week_no=1,
                inspection_type="COURSE",
                start_period=1,
                end_period=2,
            )
        )
        db.add(
            AttendanceRecord(
                id=1, task_id=1, student_id=1, effective_type="ABSENT", current_version=1
            )
        )
        db.add(
            Objection(
                id=1,
                attendance_record_id=1,
                student_id=1,
                base_attendance_version=1,
                desired_type="NORMAL",
                reason="",
                initial_status="PENDING",
                final_status="PENDING",
            )
        )
        db.commit()
        bumps = []
        monkeypatch.setattr(
            SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append(tid)
        )
        actor = CurrentUser(1, "reviewer", "学生负责人", "ACTIVE", ["STUDENT_AFFAIRS_MANAGER"], [])
        yield db, ObjectionService(db), actor, bumps


@pytest.mark.parametrize("role", ["STUDENT_AFFAIRS_MANAGER", "TEACHER_ADMIN", "SUPER_ADMIN"])
def test_manager_approval_changes_attendance_in_one_review(setup_review, role):
    db, service, actor, bumps = setup_review
    db.get(UserAccount, 1).roles = [db.scalar(select(Role).where(Role.code == role))]
    db.commit()
    result = service.final_review(
        actor,
        1,
        ObjectionFinalReviewRequest(decision="APPROVED", final_type="NORMAL", current_version=1),
        None,
    )
    assert result.final_status == "APPROVED"
    assert result.final_reviewed_username == "reviewer"
    assert result.final_reviewed_display_name == "学生负责人"
    record = db.get(AttendanceRecord, 1)
    assert (record.effective_type, record.current_version) == ("NORMAL", 2)
    version = db.scalar(select(AttendanceRecordVersion))
    assert (version.source_type, version.changed_by) == ("OBJECTION_FINAL", 1)
    assert db.scalar(select(AuditLog)).actor_user_id == 1
    assert bumps == [1]
    with pytest.raises(ConflictError):
        service.final_review(
            actor, 1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=2), None
        )


def test_manager_rejection_retains_attendance_and_operator(setup_review):
    db, service, actor, bumps = setup_review
    result = service.final_review(
        actor, 1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1), None
    )
    assert result.final_status == "REJECTED"
    assert result.final_reviewed_username == "reviewer"
    assert db.get(AttendanceRecord, 1).current_version == 1
    assert db.scalar(select(AttendanceRecordVersion)) is None
    assert bumps == []


def test_stale_attendance_cannot_be_overwritten(setup_review):
    db, service, actor, bumps = setup_review
    db.get(AttendanceRecord, 1).current_version = 2
    db.commit()
    with pytest.raises(ConflictError):
        service.final_review(
            actor,
            1,
            ObjectionFinalReviewRequest(
                decision="APPROVED", final_type="NORMAL", current_version=1
            ),
            None,
        )
    assert db.get(Objection, 1).final_status == "PENDING"
    assert db.get(AttendanceRecord, 1).effective_type == "ABSENT"
    assert bumps == []


def test_legacy_initial_review_cannot_leave_a_second_review_pending(setup_review, monkeypatch):
    db, service, actor, _ = setup_review
    # 模拟旧初核权限仍存在的账号；旧入口须明确拒绝，不能静默记录初核。
    monkeypatch.setattr(service, "_require", lambda *args: {"objection.initial_review"})
    with pytest.raises(ConflictError):
        service.initial_review(actor, 1, ObjectionInitialReviewRequest(decision="PASSED"), None)
    assert db.get(Objection, 1).initial_status == "PENDING"


def test_student_cannot_review(setup_review):
    db, service, actor, _ = setup_review
    db.get(UserAccount, 1).roles = [db.scalar(select(Role).where(Role.code == "STUDENT"))]
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service.final_review(
            actor, 1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1), None
        )


def test_old_initial_record_is_still_reviewable(setup_review):
    db, service, actor, _ = setup_review
    obj = db.get(Objection, 1)
    obj.initial_status = "PASSED"
    obj.initial_reviewed_at = datetime(2026, 10, 1)
    db.commit()
    result = service.final_review(
        actor,
        1,
        ObjectionFinalReviewRequest(decision="APPROVED", final_type="NORMAL", current_version=1),
        None,
    )
    assert result.initial_status == "PASSED"
    assert result.final_status == "APPROVED"


def test_failed_source_revision_rolls_back_review_and_attendance(setup_review, monkeypatch):
    db, service, actor, _ = setup_review

    def fail_bump(*args):
        raise RuntimeError("source revision unavailable")

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", fail_bump)
    with pytest.raises(RuntimeError):
        service.final_review(
            actor,
            1,
            ObjectionFinalReviewRequest(
                decision="APPROVED", final_type="NORMAL", current_version=1
            ),
            None,
        )
    db.rollback()  # 与 get_db 异常路径一致。
    assert db.get(Objection, 1).final_status == "PENDING"
    assert db.get(AttendanceRecord, 1).effective_type == "ABSENT"
    assert db.get(AttendanceRecord, 1).current_version == 1
    assert db.scalar(select(AttendanceRecordVersion)) is None
    assert db.scalar(select(AuditLog)) is None
