"""教师更正本人的授课考勤：范围、锁、版本链与报表源修订（T04）。

仅使用独立内存库；授权谓词、更正版本与源修订均复用生产代码路径，
不通过测试特判放行任何范围。
"""

from datetime import date

import pytest
from app.models import Base
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import FacultyStaff, TeachingStaffAssignment
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionTask
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

COURSE_DAY = date(2026, 10, 7)  # 星期三，第 6 教学周
OCC_KEY = "s:1|2026-10-07"


@pytest.fixture(name="db")
def correction_db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all([College(id=i, school_id=1, code=str(i), name=str(i)) for i in (1, 2)])
        db.add(UserAccount(id=1, display_name="教师", status="ACTIVE"))
        db.add(
            Semester(
                id=1,
                code="F",
                name="秋",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 31),
                first_monday=date(2026, 8, 31),
                total_weeks=22,
            )
        )
        db.flush()
        db.add(AcademicOffering(id="shared", school_id=1, semester_id=1, course_name="数学"))
        db.add(Course(id=1, college_id=1, course_code="M1", course_name="数学"))
        db.add(Course(id=2, college_id=2, course_code="M2", course_name="数学"))
        db.flush()
        db.add(
            TeachingClass(
                id=1,
                college_id=1,
                semester_id=1,
                course_id=1,
                class_code="1",
                class_name="数学一班",
                academic_offering_id="shared",
            )
        )
        db.add(
            TeachingClass(
                id=2,
                college_id=2,
                semester_id=1,
                course_id=2,
                class_code="2",
                class_name="数学二班",
                academic_offering_id="shared",
            )
        )
        db.add(AdministrativeClass(id=1, college_id=1, class_code="A", class_name="一班"))
        db.flush()
        db.add_all(
            [
                Student(id=1, student_no="S001", name="张一", administrative_class_id=1),
                Student(id=2, student_no="S002", name="张二", administrative_class_id=1),
            ]
        )
        db.add(FacultyStaff(school_id=1, college_id=1, staff_no="T001", name="教师", user_id=1))
        db.flush()
        for college_id, tid, key in ((1, 1, "T1"), (2, 2, "T2")):
            db.add(
                InspectionTask(
                    task_key=key,
                    semester_id=1,
                    inspection_date=COURSE_DAY,
                    week_no=6,
                    inspection_type="COURSE",
                    start_period=1,
                    end_period=2,
                    teaching_class_id=tid,
                    college_id=college_id,
                    roster_version=1,
                    occurrence_keys_snapshot=[OCC_KEY],
                    classroom_snapshot="A101",
                )
            )
        db.flush()
        from app.modules.attendance.models import AttendanceRecord

        db.add(
            AttendanceRecord(
                task_id=1, student_id=1, effective_type="LATE", current_version=1
            )
        )
        db.add(
            AttendanceRecord(
                task_id=2, student_id=2, effective_type="ABSENT", current_version=1
            )
        )
        db.commit()
        yield db
    engine.dispose()


def add_relation(db, *, local_class=None, shared=False, effective_to=None):
    db.add(
        TeachingStaffAssignment(
            staff_id=1,
            semester_id=1,
            anchor_type="LOCAL" if not shared else "SHARED",
            teaching_class_id=local_class,
            academic_offering_id=None if not shared else "shared",
            effective_from=date(2026, 9, 1),
            effective_to=effective_to,
        )
    )
    db.commit()


def staff_ref(db):
    from app.modules.identity.service import CurrentUser
    from app.modules.identity.staff_deps import CurrentStaff

    row = db.scalar(select(FacultyStaff))
    user = CurrentUser(
        id=row.user_id,
        username=None,
        display_name=row.name,
        status="ACTIVE",
        roles=[],
        permissions=[],
        pre_binding=False,
    )
    return CurrentStaff(
        user=user,
        staff_id=row.id,
        staff_no=row.staff_no,
        name=row.name,
        school_id=row.school_id,
        college_id=row.college_id,
        lock_version=row.lock_version,
    )


def request(version, attendance_type="NORMAL", reason="教师核对后更正"):
    from app.modules.attendance.schemas import AttendanceCorrectionRequest

    return AttendanceCorrectionRequest(
        current_version=version, attendance_type=attendance_type, reason=reason
    )


def service(db):
    from app.modules.attendance.staff_service import StaffTeachingAttendanceService

    return StaffTeachingAttendanceService(db)


def test_own_correction_appends_version_audit_and_bumps_responsible_college_source(db, monkeypatch):
    from app.modules.attendance.models import (
        AttendanceRecord,
        AttendanceRecordVersion,
        AttendanceSourceType,
    )
    from app.modules.audit.models import AuditLog
    from app.modules.report.source_revision import SourceRevisionService

    add_relation(db, local_class=1)
    bumps = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    ref = staff_ref(db)
    res = service(db).correct_teaching(ref.user, ref, 1, request(1), "REQ-1")
    assert res.current_version == 2 and res.effective_type == "NORMAL"
    record = db.get(AttendanceRecord, 1)
    assert record.effective_type == "NORMAL" and record.current_version == 2
    rows = db.scalars(select(AttendanceRecordVersion)).all()
    assert [(v.version_no, v.attendance_type, v.source_type, v.changed_by) for v in rows] == [
        (2, "NORMAL", AttendanceSourceType.CORRECTION.value, 1)
    ]
    # 报表源修订指向原任务负责学院的数据域，与档案所属学院无关。
    assert bumps == [(db, 1)]
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "attendance.correct"))
    assert audit is not None and audit.actor_user_id == 1


def test_stale_current_version_conflicts_and_writes_nothing(db, monkeypatch):
    from app.core.exceptions import ConflictError
    from app.modules.attendance.models import AttendanceRecord, AttendanceRecordVersion
    from app.modules.report.source_revision import SourceRevisionService

    add_relation(db, local_class=1)
    bumps = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    with pytest.raises(ConflictError):
        service(db).correct_teaching(
            staff_ref(db).user, staff_ref(db), 1, request(2), None
        )
    record = db.get(AttendanceRecord, 1)
    assert record.effective_type == "LATE" and record.current_version == 1
    assert db.scalars(select(AttendanceRecordVersion)).all() == []
    assert bumps == []


def test_record_outside_own_teaching_is_not_found(db, monkeypatch):
    add_relation(db, local_class=1)
    bumps = []
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    import pytest
    from app.core.exceptions import NotFoundError
    from app.modules.attendance.models import AttendanceRecord

    with pytest.raises(NotFoundError):
        service(db).correct_teaching(
            staff_ref(db).user, staff_ref(db), 2, request(1), None
        )
    assert db.get(AttendanceRecord, 2).effective_type == "ABSENT"
    assert bumps == []


def test_cross_college_responsible_task_is_corrected_and_bumps_that_college(db, monkeypatch):
    # 教师本人 SHARED 关系覆盖外院教学班：更正外院负责的任务，源修订仍指向该任务原学院。
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.report.source_revision import SourceRevisionService

    add_relation(db, shared=True)
    bumps = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    task = db.get(InspectionTask, 2)
    assert task.college_id == 2
    res = service(db).correct_teaching(
        staff_ref(db).user, staff_ref(db), 2, request(1, "NORMAL"), None
    )
    assert res.effective_type == "NORMAL"
    assert bumps == [(db, 2)]
    assert db.get(AttendanceRecord, 2).effective_type == "NORMAL"


def test_archived_semester_is_not_unlocked_by_teacher_entry(db, monkeypatch):
    from app.core.exceptions import ConflictError
    from app.modules.academic.models import Semester
    from app.modules.attendance.models import AttendanceRecord, AttendanceRecordVersion
    from app.modules.report.source_revision import SourceRevisionService

    add_relation(db, local_class=1)
    db.execute(
        Semester.__table__.update().where(Semester.id == 1).values(status="ARCHIVED")
    )
    db.commit()
    bumps = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append((session, tid))
    )
    with pytest.raises(ConflictError):
        service(db).correct_teaching(
            staff_ref(db).user, staff_ref(db), 1, request(1), None
        )
    record = db.get(AttendanceRecord, 1)
    assert record.effective_type == "LATE" and record.current_version == 1
    assert db.scalars(select(AttendanceRecordVersion)).all() == []
    assert bumps == []


def test_inactive_staff_profile_or_account_is_rejected(db):
    from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
    from app.modules.academic.staff_models import FacultyStaff
    from app.modules.identity.models import UserAccount

    add_relation(db, local_class=1)
    ref = staff_ref(db)
    db.execute(FacultyStaff.__table__.update().values(status="INACTIVE"))
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service(db).correct_teaching(ref.user, ref, 1, request(1), None)
    db.execute(FacultyStaff.__table__.update().values(status="ACTIVE"))
    db.commit()
    db.execute(UserAccount.__table__.update().values(status="DISABLED"))
    db.commit()
    with pytest.raises(UnauthenticatedError):
        service(db).correct_teaching(ref.user, ref, 1, request(1), None)


def test_expired_teaching_relation_is_not_found_even_if_history_matches(db):
    add_relation(db, local_class=1, effective_to=COURSE_DAY)
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        service(db).correct_teaching(staff_ref(db).user, staff_ref(db), 1, request(1), None)


def test_correction_leaves_pending_objection_open_and_reports_it(db, monkeypatch):
    """教师更正不等于结案：待处理异议保持待处理，并携带“考勤已变化”的版本落差。"""
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.objection.models import (
        Objection,
        ObjectionFinalStatus,
        ObjectionInitialStatus,
    )
    from app.modules.report.source_revision import SourceRevisionService

    # 源修订是 MySQL 方言 UPSERT，内存库只核对它被触发一次。
    bumps: list[int] = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda session, tid: bumps.append(tid)
    )
    add_relation(db, local_class=1)
    db.add(
        Objection(
            attendance_record_id=1,
            student_id=1,
            base_attendance_version=1,
            reason="现场已签到",
            desired_type="NORMAL",
            initial_status=ObjectionInitialStatus.PENDING.value,
            final_status=ObjectionFinalStatus.PENDING.value,
        )
    )
    db.commit()

    result = service(db).correct_teaching(
        staff_ref(db).user, staff_ref(db), 1, request(1, "NORMAL"), "REQ-OBJ"
    )

    obj = db.scalar(select(Objection))
    assert obj.final_status == ObjectionFinalStatus.PENDING.value
    assert obj.initial_status == ObjectionInitialStatus.PENDING.value
    assert obj.final_reviewed_by is None and obj.final_attendance_type is None
    # 发起锚点不随教师更正漂移，审核者据此得知考勤已变化。
    assert obj.base_attendance_version == 1
    assert db.get(AttendanceRecord, 1).current_version == 2
    assert result.has_objection is True
    assert result.objection_status == ObjectionFinalStatus.PENDING.value
    assert result.current_version == 2
    assert bumps == [1]
