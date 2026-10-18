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
    CourseSchedule,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import FacultyStaff, TeachingStaffAssignment
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionTask, TaskRosterVersion
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

COURSE_DAY = date(2026, 10, 7)  # 星期三，第 6 教学周
OCC_KEY = "s:1|2026-10-07"


@pytest.fixture(name="db")
def correction_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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


def page_params(page=1, page_size=20):
    from app.common.pagination import PageParams

    return PageParams(page=page, page_size=page_size)


def service(db):
    from app.modules.attendance.staff_service import StaffAttendanceSelfService

    return StaffAttendanceSelfService(db)


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


def test_own_history_is_readable_and_foreign_record_stays_hidden(db, monkeypatch):
    from app.core.exceptions import NotFoundError
    from app.modules.attendance.models import AttendanceSourceType
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, local_class=1)
    ref = staff_ref(db)
    service(db).correct_teaching(ref.user, ref, 1, request(1), "REQ-H")

    rows = service(db).record_versions(ref.user, ref, 1, "teaching")
    assert [(v.version_no, v.source_type) for v in rows] == [
        (2, AttendanceSourceType.CORRECTION.value)
    ]
    # 记录 2 属于学院 2 的教学班：本地任命不扩散，历史同样不可见。
    with pytest.raises(NotFoundError):
        service(db).record_versions(ref.user, ref, 2, "teaching")


def test_history_route_requires_the_view_and_narrows_by_teaching_relation(db, monkeypatch):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from app.modules.report.source_revision import SourceRevisionService
    from fastapi.testclient import TestClient

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, local_class=1)
    ref = staff_ref(db)
    service(db).correct_teaching(ref.user, ref, 1, request(1), "REQ-HR")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: ref.user
    with TestClient(app) as client:
        mine = client.get("/api/v1/me/attendance-records/1/versions?view=teaching")
        assert mine.status_code == 200, mine.text
        assert [row["version_no"] for row in mine.json()["data"]] == [2]
        foreign = client.get("/api/v1/me/attendance-records/2/versions?view=teaching")
        assert foreign.status_code == 404, foreign.text
        # 责任谓词不能替授课关系放行，也不允许省略视图猜测范围。
        wrong_view = client.get("/api/v1/me/attendance-records/1/versions?view=responsible")
        assert wrong_view.status_code == 404, wrong_view.text
        assert client.get("/api/v1/me/attendance-records/1/versions").status_code == 422
        assert client.get("/api/v1/me/attendance-records/1/versions?view=all").status_code == 422


# --------------------------------------------------------------------------- #
# 审查 F1：合班任务逐学生判定授课归属，不因为同任务有自己的班就放行整条名单
# --------------------------------------------------------------------------- #
def make_merged_task(db, *, provenance: bool, shared_offering: bool = True):
    """两个教学班同时间同教室合成一条任务；学生 1 只在一班，学生 2 只在二班。

    `provenance=False` 模拟本迁移之前的历史名单版本（没有冻结教学班归属）。
    `shared_offering=False` 表示两班只是恰好同堂，并未确认同一共享教务身份。
    """
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.inspection.models import (
        TaskRosterMember,
        TaskRosterMemberClass,
        TaskScheduleSource,
    )

    db.add_all(
        [
            CourseSchedule(
                id=1, teaching_class_id=1, semester_id=1, college_id=1, weekday=3,
                start_period=1, end_period=2, classroom="A101",
            ),
            CourseSchedule(
                id=2, teaching_class_id=2, semester_id=1, college_id=2, weekday=3,
                start_period=1, end_period=2, classroom="A101",
            ),
        ]
    )
    if not shared_offering:
        for tc in db.scalars(select(TeachingClass)):
            tc.academic_offering_id = None
    db.flush()
    db.add(
        InspectionTask(
            id=3, task_key="T3", semester_id=1, inspection_date=COURSE_DAY, week_no=6,
            inspection_type="COURSE", start_period=1, end_period=2, teaching_class_id=1,
            college_id=1, roster_version=1, occurrence_keys_snapshot=[OCC_KEY],
            classroom_snapshot="A101",
        )
    )
    db.flush()
    db.add_all(
        [
            TaskScheduleSource(task_id=3, teaching_class_id=1, course_schedule_id=1),
            TaskScheduleSource(task_id=3, teaching_class_id=2, course_schedule_id=2),
            TaskRosterMember(
                task_id=3, roster_version=1, student_id=1, student_no="S001", name="张一",
                class_name_snapshot="一班", administrative_class_id_snapshot=1,
            ),
            TaskRosterMember(
                task_id=3, roster_version=1, student_id=2, student_no="S002", name="张二",
                class_name_snapshot="一班", administrative_class_id_snapshot=1,
            ),
            AttendanceRecord(
                id=3, task_id=3, student_id=1, effective_type="LATE", current_version=1
            ),
            AttendanceRecord(
                id=4, task_id=3, student_id=2, effective_type="ABSENT", current_version=1
            ),
        ]
    )
    if provenance:
        db.add_all(
            [
                TaskRosterMemberClass(
                    task_id=3, roster_version=1, student_id=1, teaching_class_id=1
                ),
                TaskRosterMemberClass(
                    task_id=3, roster_version=1, student_id=2, teaching_class_id=2
                ),
            ]
        )
    db.add(TaskRosterVersion(task_id=3, version_no=1, reason="初始名单"))
    db.commit()


def _query(db):
    from app.modules.identity.service import CurrentUser
    from app.modules.inspection.staff_record_query import StaffRecordQueryService

    ref = staff_ref(db)
    row = db.scalar(select(UserAccount).where(UserAccount.id == ref.user.id))
    actor = CurrentUser(
        id=row.id, username=None, display_name=row.display_name, status="ACTIVE",
        roles=[], permissions=[],
    )
    return StaffRecordQueryService(db, actor), ref


def test_merged_task_lists_and_corrects_only_own_class_students(db, monkeypatch):
    from app.core.exceptions import NotFoundError
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, local_class=1)
    make_merged_task(db, provenance=True)
    query, ref = _query(db)

    rows, total = query.list_attendance(3, "teaching", None, page_params(1, 50))
    assert [r.student_id for r in rows] == ["1"], "二班学生不泄露给一班教师"
    assert total == 1
    assert "correct" in rows[0].allowed_actions

    with pytest.raises(NotFoundError):
        service(db).correct_teaching(ref.user, ref, 4, request(1), "REQ-F1")
    result = service(db).correct_teaching(ref.user, ref, 3, request(1), "REQ-F1-OK")
    assert (result.effective_type, result.current_version) == ("NORMAL", 2)

    card = query.get_card(3, "teaching")
    assert card.counts.total == 1, "人数与明细同一口径，不把整条合班名单算成本人应到"


def test_merged_task_without_provenance_stays_readable_but_blocks_correction(db, monkeypatch):
    from app.core.exceptions import PermissionDeniedError
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, local_class=1)
    make_merged_task(db, provenance=False)
    query, ref = _query(db)

    rows, total = query.list_attendance(3, "teaching", None, page_params(1, 50))
    assert total == 2, "历史名单没有归属记录时不封掉整条任务"
    assert all("correct" not in r.allowed_actions for r in rows)
    assert all(r.restriction_reason for r in rows)

    with pytest.raises(PermissionDeniedError):
        service(db).correct_teaching(ref.user, ref, 3, request(1), "REQ-F1-LEGACY")
    # 归属不清仍可核对历史，不需要为此给全院读取权限。
    assert service(db).record_versions(ref.user, ref, 3, "teaching") == []


def test_confirmed_shared_meeting_keeps_whole_classroom(db, monkeypatch):
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, shared=True)
    make_merged_task(db, provenance=True)
    query, ref = _query(db)

    rows, total = query.list_attendance(3, "teaching", None, page_params(1, 50))
    assert total == 2, "已确认共同授课的共享课堂保持完整能力"
    assert all("correct" in r.allowed_actions for r in rows)


def test_unconfirmed_same_room_classes_do_not_merge_authority(db, monkeypatch):
    """同教室、同名课、同节次都不是共享身份的证明：未确认映射就不产生任何授课范围。"""
    from app.core.exceptions import NotFoundError
    from app.modules.report.source_revision import SourceRevisionService

    monkeypatch.setattr(SourceRevisionService, "bump_for_task_id", lambda session, tid: None)
    add_relation(db, shared=True)
    make_merged_task(db, provenance=True, shared_offering=False)
    query, ref = _query(db)

    with pytest.raises(NotFoundError):
        query.list_attendance(3, "teaching", None, page_params(1, 50))
    with pytest.raises(NotFoundError):
        service(db).correct_teaching(ref.user, ref, 3, request(1), "REQ-F1-SHARED")
