"""教职工材料与照片逐文件授权定向回归测试。"""

from datetime import date, timedelta

import pytest
from app.core.database import get_db, utcnow
from app.core.exceptions import NotFoundError
from app.main import create_app
from app.models import Base
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.attendance.models import AttendanceRecord
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.service import FileService
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import UserAccount
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    InspectionType,
    SubmissionFile,
    TaskRosterMember,
)
from app.modules.objection.models import Objection, ObjectionFile
from app.modules.organization.models import College, School
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def staff_files_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        # 1. 学院与学期
        school = School(id=1, code="SCH", name="学校")
        db.add(school)
        db.flush()
        col1 = College(id=1, school_id=1, code="C1", name="学院一")
        col2 = College(id=2, school_id=1, code="C2", name="学院二")
        db.add_all([col1, col2])
        sem = Semester(
            id=1,
            code="2026-FALL",
            name="2026秋",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
            first_monday=date(2026, 8, 31),
            total_weeks=22,
        )
        db.add(sem)
        db.flush()

        course1 = Course(id=1, college_id=1, course_code="CS1", course_name="计算概论")
        course2 = Course(id=2, college_id=2, course_code="EE1", course_name="电路原理")
        db.add_all([course1, course2])
        db.flush()

        tc1 = TeachingClass(
            id=1,
            college_id=1,
            semester_id=1,
            course_id=1,
            class_code="TC1",
            class_name="计算概论1班",
            teacher_name="李老师",
        )
        tc2 = TeachingClass(
            id=2,
            college_id=2,
            semester_id=1,
            course_id=2,
            class_code="TC2",
            class_name="电路原理1班",
            teacher_name="外院张老师",
        )
        cls_a = AdministrativeClass(id=1, college_id=1, class_code="A", class_name="计科1班")
        db.add_all([tc1, tc2, cls_a])
        db.flush()

        # 2. 学生与账号
        student1 = Student(id=1, student_no="S001", name="张三", administrative_class_id=1)
        db.add(student1)
        u_teacher = UserAccount(id=10, display_name="李老师", status="ACTIVE")
        u_counselor = UserAccount(id=20, display_name="王辅导员", status="ACTIVE")
        u_volunteer = UserAccount(id=40, display_name="志愿者小李", status="ACTIVE")
        db.add_all([u_teacher, u_counselor, u_volunteer])
        db.flush()

        staff_t = FacultyStaff(
            id=101,
            school_id=1,
            college_id=1,
            staff_no="T001",
            name="李老师",
            user_id=10,
            status="ACTIVE",
        )
        staff_c = FacultyStaff(
            id=102,
            school_id=1,
            college_id=1,
            staff_no="C001",
            name="王辅导员",
            user_id=20,
            status="ACTIVE",
        )
        db.add_all([staff_t, staff_c])
        db.flush()

        # 任课与责任
        db.add(
            TeachingStaffAssignment(
                staff_id=101,
                semester_id=1,
                anchor_type="LOCAL",
                teaching_class_id=1,
                effective_from=date(2026, 9, 1),
            )
        )
        db.add(
            ClassStaffResponsibility(
                staff_id=102,
                administrative_class_id=1,
                duty="COUNSELOR",
                effective_from=date(2026, 9, 1),
            )
        )

        # 3. 任务与材料
        # 任务 1：学院1内部课程，张三选课
        task1 = InspectionTask(
            id=1,
            college_id=1,
            task_key="TASK-COL1",
            semester_id=1,
            inspection_date=date(2026, 10, 19),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=1,
            end_period=2,
            teaching_class_id=1,
            course_name_snapshot="计算概论",
            classroom_snapshot="教101",
            expected_count_snapshot=1,
            expected_count_current=1,
            roster_version=1,
        )
        # 任务 2：学院2课程，张三跨选外院课（被外院检查）
        task2 = InspectionTask(
            id=2,
            college_id=2,
            task_key="TASK-COL2",
            semester_id=1,
            inspection_date=date(2026, 10, 19),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=3,
            end_period=4,
            teaching_class_id=2,
            course_name_snapshot="电路原理",
            classroom_snapshot="教202",
            expected_count_snapshot=1,
            expected_count_current=1,
            roster_version=1,
        )
        db.add_all([task1, task2])
        db.flush()

        db.add_all([
            TaskRosterMember(
                task_id=1,
                roster_version=1,
                student_id=1,
                student_no="S001",
                name="张三",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计科1班",
            ),
            TaskRosterMember(
                task_id=2,
                roster_version=1,
                student_id=1,
                student_no="S001",
                name="张三",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计科1班",
            ),
        ])

        # 考勤
        att1 = AttendanceRecord(task_id=1, student_id=1, effective_type="ABSENT", current_version=1)
        att2 = AttendanceRecord(task_id=2, student_id=1, effective_type="ABSENT", current_version=1)
        db.add_all([att1, att2])
        db.flush()

        # 提交与照片
        sub1 = InspectionSubmission(
            id=1,
            task_id=1,
            attempt_no=1,
            volunteer_user_id=40,
            roster_version=1,
            result="ABNORMAL",
            review_status="APPROVED",
            submitted_at=utcnow(),
        )
        sub2 = InspectionSubmission(
            id=2,
            task_id=2,
            attempt_no=1,
            volunteer_user_id=40,
            roster_version=1,
            result="ABNORMAL",
            review_status="APPROVED",
            submitted_at=utcnow(),
        )
        db.add_all([sub1, sub2])
        db.flush()

        photo1 = FileObject(
            id=101,
            object_key="photos/task1.jpg",
            category=FileCategory.SUBMISSION_PHOTO.value,
            content_type="image/jpeg",
            size_bytes=1024,
            sha256="0" * 64,
            uploader_user_id=40,
            status=FileStatus.READY.value,
            expires_at=utcnow() + timedelta(days=7),
        )
        photo2 = FileObject(
            id=102,
            object_key="photos/task2.jpg",
            category=FileCategory.SUBMISSION_PHOTO.value,
            content_type="image/jpeg",
            size_bytes=1024,
            sha256="0" * 64,
            uploader_user_id=40,
            status=FileStatus.READY.value,
            expires_at=utcnow() + timedelta(days=7),
        )
        db.add_all([photo1, photo2])
        db.flush()

        db.add_all([
            SubmissionFile(submission_id=1, file_id=101),
            SubmissionFile(submission_id=2, file_id=102),
        ])

        # 异议与证明材料
        obj1 = Objection(
            id=1,
            attendance_record_id=att1.id,
            student_id=1,
            base_attendance_version=1,
            reason="生病请假",
            desired_type="LEAVE",
            initial_status="PENDING",
            final_status="PENDING",
        )
        obj2 = Objection(
            id=2,
            attendance_record_id=att2.id,
            student_id=1,
            base_attendance_version=1,
            reason="参加竞赛",
            desired_type="LEAVE",
            initial_status="PENDING",
            final_status="PENDING",
        )
        db.add_all([obj1, obj2])
        db.flush()

        proof1 = FileObject(
            id=201,
            object_key="proofs/obj1.jpg",
            category=FileCategory.OBJECTION_PROOF.value,
            content_type="image/jpeg",
            size_bytes=1024,
            sha256="0" * 64,
            uploader_user_id=10,
            status=FileStatus.READY.value,
            expires_at=utcnow() + timedelta(days=7),
        )
        proof2 = FileObject(
            id=202,
            object_key="proofs/obj2.jpg",
            category=FileCategory.OBJECTION_PROOF.value,
            content_type="image/jpeg",
            size_bytes=1024,
            sha256="0" * 64,
            uploader_user_id=10,
            status=FileStatus.READY.value,
            expires_at=utcnow() + timedelta(days=7),
        )
        db.add_all([proof1, proof2])
        db.flush()

        db.add_all([
            ObjectionFile(objection_id=1, file_id=201),
            ObjectionFile(objection_id=2, file_id=202),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_teacher_photo_access(staff_files_db):
    """任课教师可访问本人授课任务的现场照片，不可访问他人任务照片。"""
    db = staff_files_db
    service = FileService(db)
    teacher = CurrentUser(
        id=10,
        username="teacher",
        display_name="李老师",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )

    photo1 = db.get(FileObject, 101)
    photo2 = db.get(FileObject, 102)

    # 李老师教 Task 1，可看 photo1
    assert service.can_access(teacher, photo1) is True
    # 李老师不教 Task 2，不可看 photo2
    assert service.can_access(teacher, photo2) is False


def test_counselor_photo_and_objection_access_cross_college_denial(staff_files_db):
    """照片和异议材料逐文件访问授权，跨院只读汇总不隐含材料权限。"""
    db = staff_files_db
    service = FileService(db)
    counselor = CurrentUser(
        id=20,
        username="counselor",
        display_name="王辅导员",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )

    photo1 = db.get(FileObject, 101)
    photo2 = db.get(FileObject, 102)
    proof1 = db.get(FileObject, 201)
    proof2 = db.get(FileObject, 202)

    # 1. 现场照片
    # Task 1 是本院任务且包含辅导员学生：允许访问
    assert service.can_access(counselor, photo1) is True
    # Task 2 是外院任务（虽然包含本班学生）：跨院只读汇总不隐含材料权限，拒绝访问！
    assert service.can_access(counselor, photo2) is False

    # 2. 异议材料
    # Obj 1 是本院任务的异议：允许访问
    assert service.can_access(counselor, proof1) is True
    # Obj 2 是外院任务的异议：跨院不隐含材料权限，拒绝访问！
    assert service.can_access(counselor, proof2) is False


def test_file_access_revocation_immediately_rejects(staff_files_db):
    """撤权后下一次读取或签名拒绝。"""
    db = staff_files_db
    service = FileService(db)
    counselor = CurrentUser(
        id=20,
        username="counselor",
        display_name="王辅导员",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )

    photo1 = db.get(FileObject, 101)
    assert service.can_access(counselor, photo1) is True

    # 撤权：将王辅导员的责任关系结束
    resp = db.query(ClassStaffResponsibility).filter_by(staff_id=102).first()
    resp.effective_to = date(2026, 9, 15)
    db.commit()

    # 下一次判断立即拒绝
    assert service.can_access(counselor, photo1) is False
    with pytest.raises(NotFoundError):
        service.get_access(counselor, 101)


def test_http_file_access_contract(staff_files_db):
    """通过 HTTP GET /api/v1/files/{file_id}/access 端点验证。"""
    db = staff_files_db
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=20,
        username="counselor",
        display_name="王辅导员",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )

    with TestClient(app) as client:
        # 有权访问本院照片
        res1 = client.get("/api/v1/files/101/access")
        assert res1.status_code == 200
        assert "url" in res1.json()["data"]

        # 无权访问跨院照片 (404)
        res2 = client.get("/api/v1/files/102/access")
        assert res2.status_code == 404
