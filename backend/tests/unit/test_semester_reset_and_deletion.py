from datetime import date

import pytest
from app.core.database import Base
from app.core.exceptions import ConflictError
from app.core.permissions import PermissionCode, RoleCode
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    Student,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.schemas import (
    SemesterResetDataRequest,
    StudentBatchDeleteRequest,
)
from app.modules.academic.service import AcademicService
from app.modules.identity.models import Permission, Role, RolePermission, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _setup_admin(session: Session) -> CurrentUser:
    admin_user = UserAccount(
        id=1, username="admin", display_name="超级管理员", status="ACTIVE"
    )
    session.add(admin_user)
    session.flush()

    role = Role(code=RoleCode.SUPER_ADMIN.value, name="超级管理员")
    session.add(role)
    session.flush()

    ur = UserRole(user_id=1, role_id=role.id)
    session.add(ur)
    session.flush()

    for pcode in [PermissionCode.ACADEMIC_MANAGE.value, PermissionCode.STUDENT_MANAGE.value]:
        p = Permission(code=pcode, name=pcode)
        session.add(p)
        session.flush()
        rp = RolePermission(role_id=role.id, permission_id=p.id)
        session.add(rp)
    session.flush()

    return CurrentUser(
        id=1,
        username="admin",
        display_name="Admin",
        status="ACTIVE",
        roles=[RoleCode.SUPER_ADMIN.value],
        permissions=[PermissionCode.ACADEMIC_MANAGE.value, PermissionCode.STUDENT_MANAGE.value],
    )


def test_reset_semester_data(db_session: Session):
    actor = _setup_admin(db_session)
    service = AcademicService(db_session)

    # 1. 准备学期与业务数据
    sem = Semester(
        id=1,
        code="2026-2027-1",
        name="2026-2027学年秋季学期",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 15),
        first_monday=date(2026, 9, 7),
        status="ACTIVE",
    )
    db_session.add(sem)
    course = Course(id=1, course_code="CS101", course_name="计算机导论", status="ACTIVE")
    db_session.add(course)
    tc = TeachingClass(id=1, semester_id=1, course_id=1, class_name="CS101-01班")
    db_session.add(tc)
    sched = CourseSchedule(
        id=1, semester_id=1, teaching_class_id=1, weekday=1, start_period=1, end_period=2
    )
    db_session.add(sched)
    db_session.flush()
    week = CourseScheduleWeek(schedule_id=1, week_no=1)
    db_session.add(week)

    cls = AdministrativeClass(id=1, class_code="CLASS01", class_name="软件2401")
    stu = Student(id=1, student_no="2024001", name="张三", administrative_class_id=1)
    db_session.add_all([cls, stu])
    db_session.flush()

    vq = VolunteerQualification(id=1, semester_id=1, student_id=1, enabled=True)
    db_session.add(vq)

    task = InspectionTask(
        id=1,
        task_key="TASK-01",
        semester_id=1,
        inspection_date=date(2026, 9, 7),
        week_no=1,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        teaching_class_id=1,
    )
    db_session.add(task)
    db_session.flush()

    # 2. 校验错误确认名称拦截
    with pytest.raises(ConflictError):
        service.reset_semester_data(
            actor, 1, SemesterResetDataRequest(confirm_name="错误的学期名称")
        )

    # 3. 正确确认名称重置
    res = service.reset_semester_data(
        actor, 1, SemesterResetDataRequest(confirm_name="2026-2027学年秋季学期")
    )
    assert res.cleared_tasks_count == 1
    assert res.cleared_schedules_count == 1
    assert res.cleared_teaching_classes_count == 1
    assert res.cleared_volunteer_qualifications_count == 1

    # 验证任务、课表、教学班、志愿者已清理
    assert db_session.get(InspectionTask, 1) is None
    assert db_session.get(CourseSchedule, 1) is None
    assert db_session.get(TeachingClass, 1) is None
    assert db_session.get(VolunteerQualification, 1) is None

    # 但学期本身、学生、班级、课程底册依然完整保留
    assert db_session.get(Semester, 1) is not None
    assert db_session.get(Student, 1) is not None
    assert db_session.get(AdministrativeClass, 1) is not None
    assert db_session.get(Course, 1) is not None


def test_delete_admin_class_and_cascade_students(db_session: Session):
    actor = _setup_admin(db_session)
    service = AcademicService(db_session)

    cls = AdministrativeClass(id=10, class_code="CLASS10", class_name="测试班级10")
    stu1 = Student(id=101, student_no="STU101", name="学生A", administrative_class_id=10)
    stu2 = Student(id=102, student_no="STU102", name="学生B", administrative_class_id=10)
    db_session.add_all([cls, stu1, stu2])
    db_session.commit()

    # 不开启级联删除时，有学生应报错
    with pytest.raises(ConflictError) as exc_info:
        service.delete_admin_class(actor, 10, cascade_students=False)
    assert "尚有 2 名学生档案" in str(exc_info.value)

    # 开启级联删除
    del_res = service.delete_admin_class(actor, 10, cascade_students=True)
    assert del_res.deleted_students_count == 2
    assert db_session.get(AdministrativeClass, 10) is None
    assert db_session.get(Student, 101) is None
    assert db_session.get(Student, 102) is None


def test_delete_student_and_batch_delete(db_session: Session):
    actor = _setup_admin(db_session)
    service = AcademicService(db_session)

    cls = AdministrativeClass(id=20, class_code="CLASS20", class_name="软件20班")
    stu1 = Student(id=201, student_no="STU201", name="独立学生1", administrative_class_id=20)
    stu2 = Student(id=202, student_no="STU202", name="独立学生2", administrative_class_id=20)
    stu_bound = Student(id=203, student_no="STU203", name="已绑定学生", administrative_class_id=20)
    db_session.add_all([cls, stu1, stu2, stu_bound])
    db_session.flush()

    # 为 stu_bound 绑定系统账号
    user = UserAccount(id=203, student_id=203, display_name="绑定微信学生")
    db_session.add(user)
    db_session.commit()

    # 1. 尝试删除已绑定账号的学生，应被拦截
    with pytest.raises(ConflictError) as exc_bound:
        service.delete_student(actor, 203)
    assert "已绑定账号" in str(exc_bound.value)

    # 2. 单条删除未绑定学生
    service.delete_student(actor, 201)
    assert db_session.get(Student, 201) is None

    # 3. 批量删除
    batch_res = service.batch_delete_students(
        actor, StudentBatchDeleteRequest(student_ids=[202])
    )
    assert batch_res.deleted_count == 1
    assert db_session.get(Student, 202) is None
