"""教职工优化的真实 MySQL 查询和绑定竞争；仅由隔离 *_test 夹具运行。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
from threading import Barrier

import openpyxl
import pytest
from app.common.pagination import PageParams
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.core.security import hash_token
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.occurrence_location import OccurrenceLocationService
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_binding import StaffBindingService
from app.modules.identity.staff_binding_models import StaffBindingToken
from app.modules.identity.staff_deps import require_current_staff
from app.modules.inspection.models import (
    InspectionTask,
    TaskRosterMember,
    TaskRosterMemberClass,
    TaskScheduleSource,
)
from app.modules.inspection.staff_record_query import StaffRecordQueryService
from app.modules.organization.models import College, School
from sqlalchemy import func, null, select, text
from sqlalchemy.orm import Session

DAY = date(2026, 10, 7)
KEY = f"s:1|{DAY}"


@pytest.fixture
def staff_data(session):
    db = session
    db.add(School(id=1, code="S", name="Synthetic"))
    db.flush()
    db.add(College(id=1, school_id=1, code="C", name="Synthetic"))
    db.add_all([UserAccount(id=i, display_name=f"User {i}", status="ACTIVE") for i in (1, 2, 3)])
    db.add(Semester(
        id=1, code="F", name="Synthetic", start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 31), first_monday=date(2026, 8, 31), total_weeks=22,
    ))
    db.add(Role(id=1, code="SUPER_ADMIN", name="Admin"))
    db.flush()
    db.add(UserRole(user_id=3, role_id=1))
    for i in (1, 2):
        db.add(AdministrativeClass(id=i, college_id=1, class_code=str(i), class_name=str(i)))
        db.add(Course(id=i, college_id=1, course_code=str(i), course_name=str(i)))
    db.flush()
    for i in (1, 2):
        db.add(Student(id=i, student_no=f"00{i}", name=f"Student {i}", administrative_class_id=i))
        db.add(TeachingClass(
            id=i, college_id=1, semester_id=1, course_id=i,
            class_code=str(i), class_name=f"Class {i}",
        ))
    db.add_all([FacultyStaff(
        id=i, school_id=1, college_id=1, staff_no=f"T00{i}", name=f"Staff {i}",
        user_id=1 if i == 1 else None,
    ) for i in (1, 2, 3)])
    db.flush()
    db.add(TeachingStaffAssignment(
        staff_id=1, semester_id=1, anchor_type="LOCAL", teaching_class_id=1,
        effective_from=date(2026, 9, 1),
    ))
    db.add(ClassStaffResponsibility(
        staff_id=1, administrative_class_id=1, duty="COUNSELOR",
        effective_from=date(2026, 9, 1),
    ))
    for i in (1, 2):
        db.add(CourseSchedule(
            id=i, teaching_class_id=i, semester_id=1, college_id=1,
            weekday=3, start_period=1, end_period=2, classroom="A101",
        ))
    db.flush()
    db.add_all([CourseScheduleWeek(schedule_id=i, week_no=6) for i in (1, 2)])
    db.add(InspectionTask(
        id=1, task_key="MERGED", semester_id=1, college_id=1, inspection_date=DAY,
        week_no=6, inspection_type="COURSE", start_period=1, end_period=2,
        teaching_class_id=1, roster_version=1, occurrence_keys_snapshot=[KEY],
    ))
    db.flush()
    for i in (1, 2):
        db.add(TaskScheduleSource(task_id=1, teaching_class_id=i, course_schedule_id=i))
        db.add(TaskRosterMember(
            task_id=1, roster_version=1, student_id=i, student_no=f"00{i}", name=f"Student {i}",
            administrative_class_id_snapshot=i,
        ))
        db.add(TaskRosterMemberClass(
            task_id=1, roster_version=1, student_id=i, teaching_class_id=i,
        ))
        db.add(AttendanceRecord(
            task_id=1, student_id=i, effective_type="NORMAL" if i == 1 else "ABSENT",
            current_version=1,
        ))
    db.commit()
    return db


def actor(user_id=1):
    return CurrentUser(
        user_id, None, "Synthetic", "ACTIVE", ["SUPER_ADMIN"] if user_id == 3 else [], []
    )


def token(db, staff_id=2, code="ABC234", status="UNUSED"):
    row = StaffBindingToken(
        staff_id=staff_id, token_hash=hash_token(code), status=status,
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()
    return row.id


@pytest.mark.parametrize("view", ["teaching", "responsible"])
def test_mysql_scoped_cards_summary_export_and_explain(staff_data, view):
    db = staff_data
    svc = StaffRecordQueryService(db, actor())
    cards, total = svc.list_cards(view, PageParams(page=1, page_size=20))
    assert total == 1 and cards[0].counts.total == 1
    items, count = svc.list_attendance(1, view, None, PageParams(page=1, page_size=20))
    assert count == 1 and items[0].student_no == "001"
    assert svc.get_summary(view).student_counts.total == 1
    data, _ = svc.export_excel(view)
    book = openpyxl.load_workbook(BytesIO(data), read_only=True)
    rows = list(book.active.values)
    book.close()
    assert len(rows) == 2 and rows[1][8] == "001"
    stmt = svc._attendance_query(view, DAY).with_only_columns(
        AttendanceRecord.effective_type, func.count()
    ).where(AttendanceRecord.task_id == 1).group_by(AttendanceRecord.effective_type)
    sql = str(stmt.compile(db.get_bind(), compile_kwargs={"literal_binds": True}))
    assert db.execute(text("EXPLAIN " + sql)).all()


def test_mysql_calendar_matches_sql_null_json_null_and_empty_snapshot(staff_data):
    db = staff_data
    for i, snapshot in enumerate((None, [], null()), start=2):
        db.add(InspectionTask(
            id=i, task_key=f"LEGACY-{i}", semester_id=1, college_id=1,
            inspection_date=DAY, week_no=6, inspection_type="COURSE", start_period=1,
            end_period=2, teaching_class_id=1, course_schedule_id=1,
            occurrence_keys_snapshot=snapshot,
        ))
    db.commit()
    ref = require_current_staff(actor(), db)
    result = OccurrenceLocationService(db).occurrence_calendar(ref, date_from=DAY, date_to=DAY)
    assert result.total == 1 and result.items[0].task_ids == ["1", "2", "3", "4"]


def test_mysql_duplicate_code_on_another_profile_does_not_block_binding(staff_data):
    db = staff_data
    token(db, staff_id=2)
    token(db, staff_id=3)
    assert StaffBindingService(db).redeem(
        user_id=2, staff_no="T003", binding_code="ABC234"
    )["staff_id"] == "3"
    assert db.get(FacultyStaff, 2).user_id is None


@pytest.mark.parametrize("same_account", [False, True])
def test_mysql_concurrent_redemption_has_one_winner(staff_data, engine, same_account):
    db = staff_data
    token(db, staff_id=2)
    if same_account:
        token(db, staff_id=3, code="XYZ789")
    barrier = Barrier(2)

    def redeem(user_id, number, code):
        with Session(engine) as other:
            other.execute(text("SET SESSION innodb_lock_wait_timeout=8"))
            barrier.wait(timeout=10)
            try:
                StaffBindingService(other).redeem(
                    user_id=user_id, staff_no=number, binding_code=code
                )
                return 200
            except AppError as exc:
                return exc.http_status

    second = (2, "T003", "XYZ789") if same_account else (3, "T002", "ABC234")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(redeem, 2, "T002", "ABC234"), pool.submit(redeem, *second)]
        assert sorted(f.result(timeout=20) for f in futures) == [200, 409]
    db.rollback()
    assert db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "staff.bind")
    ) == 1


def test_mysql_revoke_and_redeem_follow_the_same_profile_lock(staff_data, engine):
    db = staff_data
    token_id = token(db)
    barrier = Barrier(2)

    def perform(revoke):
        with Session(engine) as other:
            other.execute(text("SET SESSION innodb_lock_wait_timeout=8"))
            barrier.wait(timeout=10)
            try:
                svc = StaffBindingService(other, college_id=1)
                if revoke:
                    svc.revoke_token(actor=actor(3), token_id=token_id)
                else:
                    svc.redeem(user_id=2, staff_no="T002", binding_code="ABC234")
                return 200
            except AppError as exc:
                return exc.http_status

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(perform, True), pool.submit(perform, False)
        assert sorted([a.result(timeout=20), b.result(timeout=20)]) == [200, 409]
    db.rollback()
    db.expire_all()
    row = db.get(StaffBindingToken, token_id)
    assert (row.status, db.get(FacultyStaff, 2).user_id) in [("USED", 2), ("EXPIRED", None)]
