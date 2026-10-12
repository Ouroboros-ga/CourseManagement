from datetime import date, datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.core.permissions import RoleCode
from app.modules.academic.models import (
    AdministrativeClass,
    Semester,
    Student,
    VolunteerQualification,
)
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    InspectionAssignment,
    InspectionTask,
    TaskRosterMember,
    TaskRosterVersion,
)
from app.modules.inspection.service import InspectionService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_list_semester_volunteers_and_delete_tasks(db_session: Session):
    actor = CurrentUser(
        id=1,
        username="admin",
        display_name="Admin",
        status="ACTIVE",
        roles=[RoleCode.SUPER_ADMIN.value],
        permissions=["inspection.generate", "inspection.read", "assignment.manage"],
    )

    from app.modules.identity.models import Permission, RolePermission

    admin_user = UserAccount(
        id=1, username="admin", display_name="超级管理员", status="ACTIVE"
    )
    db_session.add(admin_user)
    db_session.flush()
    role = Role(code=RoleCode.SUPER_ADMIN.value, name="超级管理员")
    db_session.add(role)
    db_session.flush()
    ur = UserRole(user_id=1, role_id=role.id)
    db_session.add(ur)
    db_session.flush()

    p = Permission(code="inspection.generate", name="生成/删除任务")
    db_session.add(p)
    db_session.flush()
    rp = RolePermission(role_id=role.id, permission_id=p.id)
    db_session.add(rp)
    db_session.flush()

    sem = Semester(
        code="2026-SPRING",
        name="2026春季",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 7, 1),
        total_weeks=18,
        first_monday=date(2026, 3, 2),
        status="ACTIVE",
    )
    db_session.add(sem)
    db_session.flush()

    ac = AdministrativeClass(
        class_code="CS2401",
        class_name="计科2401班",
        grade_year=2024,
        major_name="计算机科学与技术",
        college="信息工程学院",
        status="ACTIVE",
    )
    db_session.add(ac)
    db_session.flush()

    s1 = Student(
        student_no="2024001",
        name="张三",
        administrative_class_id=ac.id,
        status="ACTIVE",
    )
    s2 = Student(
        student_no="2024002",
        name="李四",
        administrative_class_id=ac.id,
        status="ACTIVE",
    )
    db_session.add_all([s1, s2])
    db_session.flush()

    # 赋予张三当前学期志愿者资格
    vq = VolunteerQualification(
        semester_id=sem.id,
        student_id=s1.id,
        enabled=True,
        created_by=1,
    )
    db_session.add(vq)
    db_session.commit()

    service = InspectionService(db_session)

    # 1. 测试本学期已有志愿者候选查询
    vols = service.list_semester_volunteers(sem.id, keyword="张三")
    assert len(vols) == 1
    assert vols[0].name == "张三"
    assert vols[0].student_no == "2024001"
    assert vols[0].class_name == "计科2401班"
    assert vols[0].user_id != ""

    # 测试关键字未匹配
    vols_none = service.list_semester_volunteers(sem.id, keyword="王五")
    assert len(vols_none) == 0

    # 2. 创建查课任务与名单
    task1 = InspectionTask(
        task_key=f"task_sem_{sem.id}_1",
        semester_id=sem.id,
        inspection_date=date(2026, 3, 10),
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        course_name_snapshot="高等数学A",
        classroom_snapshot="1-101",
        expected_count_current=30,
        expected_count_snapshot=30,
        lock_version=0,
    )
    task2 = InspectionTask(
        task_key=f"task_sem_{sem.id}_2",
        semester_id=sem.id,
        inspection_date=date(2026, 3, 10),
        week_no=2,
        inspection_type="COURSE",
        start_period=3,
        end_period=4,
        course_name_snapshot="线性代数",
        classroom_snapshot="1-102",
        expected_count_current=25,
        expected_count_snapshot=25,
        lock_version=0,
    )
    db_session.add_all([task1, task2])
    db_session.flush()

    rv = TaskRosterVersion(task_id=task1.id, version_no=1)
    db_session.add(rv)
    db_session.flush()
    rm = TaskRosterMember(
        task_id=task1.id,
        roster_version=1,
        student_id=s2.id,
        student_no=s2.student_no,
        name=s2.name,
    )
    db_session.add(rm)
    asgn = InspectionAssignment(
        task_id=task1.id,
        volunteer_user_id=int(vols[0].user_id),
        assign_method="MANUAL",
        lock_version=0,
    )
    db_session.add(asgn)
    db_session.commit()

    # 3. 测试批量删除任务（task1 带名单与受派关系，task2 为普通任务）
    deleted_ids = service.delete_tasks(actor, [task1.id, task2.id], reason="测试批量删除")
    assert set(deleted_ids) == {task1.id, task2.id}

    # 验证任务已不存在
    assert db_session.get(InspectionTask, task1.id) is None
    assert db_session.get(InspectionTask, task2.id) is None
    # 验证级联关联已清理
    assert (
        db_session.query(InspectionAssignment).filter_by(task_id=task1.id).first() is None
    )
    assert (
        db_session.query(TaskRosterVersion).filter_by(task_id=task1.id).first() is None
    )
    assert (
        db_session.query(TaskRosterMember).filter_by(task_id=task1.id).first() is None
    )


def test_task_assemble_with_head_teacher_and_counselor(db_session: Session):
    from app.modules.academic.models import TeachingClass, TeachingClassStudent, Course

    sem = Semester(
        id=20,
        code="2026-AUTUMN",
        name="2026秋",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 15),
        first_monday=date(2026, 9, 7),
        status="ACTIVE",
    )
    ac = AdministrativeClass(
        id=10,
        class_code="SE2501",
        class_name="软工2501",
        head_teacher="张班主任",
        counselor="李辅导员",
        status="ACTIVE",
    )
    c = Course(id=1, course_code="CS101", course_name="算法分析", status="ACTIVE")
    tc = TeachingClass(
        id=100,
        semester_id=sem.id,
        course_id=c.id,
        class_code="TC100",
        class_name="软工2501-算法分析",
        teacher_name=None,
        status="ACTIVE",
    )
    s = Student(id=50, student_no="20260050", name="测试生", administrative_class_id=ac.id, status="ACTIVE")
    tcs = TeachingClassStudent(teaching_class_id=tc.id, student_id=s.id)

    task = InspectionTask(
        id=500,
        task_key="sem20_d2026-09-10_COURSE_p1_p2_cs1",
        semester_id=sem.id,
        inspection_date=date(2026, 9, 10),
        week_no=1,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        teaching_class_id=tc.id,
        class_name_snapshot="软工2501-算法分析",
        course_name_snapshot="算法分析",
        classroom_snapshot="1-201",
        teacher_name_snapshot=None,
        expected_count_current=30,
        expected_count_snapshot=30,
        lock_version=0,
    )

    db_session.add_all([sem, ac, c, tc, s, tcs, task])
    db_session.flush()

    service = InspectionService(db_session)
    res = service._assemble_tasks([task])
    assert len(res) == 1
    item = res[0]
    assert item.head_teacher == "张班主任"
    assert item.counselor == "李辅导员"
    assert item.administrative_classes == ["软工2501"]
    # 优先显示班主任兜底
    assert item.effective_teacher == "张班主任"

