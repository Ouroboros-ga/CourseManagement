"""教职工只读卡片、明细、统计与导出定向回归测试。"""

from datetime import date, datetime
from io import BytesIO

import openpyxl
import pytest
from app.core.database import get_db
from app.main import create_app
from app.models import Base
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import UserAccount
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    InspectionTask,
    InspectionType,
    TaskRosterMember,
)
from app.modules.organization.models import College, School
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def staff_records_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        # 1. 基础主数据
        school = School(id=1, code="SCH", name="学校")
        db.add(school)
        db.flush()

        college1 = College(id=1, school_id=1, code="C1", name="学院一")
        college2 = College(id=2, school_id=1, code="C2", name="学院二")
        db.add_all([college1, college2])
        db.flush()

        semester = Semester(
            id=1,
            code="2026-FALL",
            name="2026秋",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
            first_monday=date(2026, 8, 31),
            total_weeks=22,
        )
        db.add(semester)

        offering = AcademicOffering(
            id="shared-math", school_id=1, semester_id=1, course_name="高数"
        )
        db.add(offering)

        course1 = Course(id=1, college_id=1, course_code="MATH1", course_name="高等数学A")
        course2 = Course(id=2, college_id=2, course_code="MATH2", course_name="高等数学B")
        db.add_all([course1, course2])
        db.flush()

        tc1 = TeachingClass(
            id=1,
            college_id=1,
            semester_id=1,
            course_id=1,
            class_code="TC1",
            class_name="高数教学班1",
            teacher_name="李老师",
            academic_offering_id="shared-math",
        )
        tc2 = TeachingClass(
            id=2,
            college_id=2,
            semester_id=1,
            course_id=2,
            class_code="TC2",
            class_name="高数教学班2",
            teacher_name="李老师",
            academic_offering_id="shared-math",
        )
        tc3 = TeachingClass(
            id=3,
            college_id=1,
            semester_id=1,
            course_id=1,
            class_code="TC3",
            class_name="高数教学班3",
            teacher_name="李老师",
            academic_offering_id=None,
        )
        db.add_all([tc1, tc2, tc3])

        class_a = AdministrativeClass(id=1, college_id=1, class_code="A", class_name="计算机1班")
        class_b = AdministrativeClass(id=2, college_id=1, class_code="B", class_name="软件2班")
        class_c = AdministrativeClass(id=3, college_id=2, class_code="C", class_name="外院3班")
        db.add_all([class_a, class_b, class_c])
        db.flush()

        # 2. 学生
        s1 = Student(id=1, student_no="S001", name="张三", administrative_class_id=1)
        s2 = Student(id=2, student_no="S002", name="李四", administrative_class_id=1)
        s3 = Student(id=3, student_no="S003", name="王五", administrative_class_id=2)
        s4 = Student(id=4, student_no="S004", name="赵六", administrative_class_id=3)
        db.add_all([s1, s2, s3, s4])

        # 3. 账号与教职工档案
        u_teacher = UserAccount(id=10, display_name="李老师", status="ACTIVE")
        u_counselor = UserAccount(id=20, display_name="王辅导员", status="ACTIVE")
        u_stranger = UserAccount(id=30, display_name="路人", status="ACTIVE")
        db.add_all([u_teacher, u_counselor, u_stranger])
        db.flush()

        staff_teacher = FacultyStaff(
            id=101,
            school_id=1,
            college_id=1,
            staff_no="T001",
            name="李老师",
            user_id=10,
            status="ACTIVE",
        )
        staff_counselor = FacultyStaff(
            id=102,
            school_id=1,
            college_id=1,
            staff_no="C001",
            name="王辅导员",
            user_id=20,
            status="ACTIVE",
        )
        db.add_all([staff_teacher, staff_counselor])
        db.flush()

        # 4. 任务与名单
        # Task 1: 学院1的高数课 (TC1), 查课日 2026-10-19. 名单包含 s1, s2, s3
        task1 = InspectionTask(
            id=1,
            college_id=1,
            task_key="TASK-1",
            semester_id=1,
            inspection_date=date(2026, 10, 19),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=1,
            end_period=2,
            teaching_class_id=1,
            course_name_snapshot="高等数学A",
            classroom_snapshot="教101",
            expected_count_snapshot=3,
            expected_count_current=3,
            roster_version=1,
        )
        # Task 2: 学院2的高数课 (TC2), 查课日 2026-10-19. 名单包含 s4
        task2 = InspectionTask(
            id=2,
            college_id=2,
            task_key="TASK-2",
            semester_id=1,
            inspection_date=date(2026, 10, 19),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=1,
            end_period=2,
            teaching_class_id=2,
            course_name_snapshot="高等数学B",
            classroom_snapshot="教202",
            expected_count_snapshot=1,
            expected_count_current=1,
            roster_version=1,
        )
        # Task 3: 未形成考勤任务 (TC3), 查课日 2026-10-20
        task3 = InspectionTask(
            id=3,
            college_id=1,
            task_key="TASK-3",
            semester_id=1,
            inspection_date=date(2026, 10, 20),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=3,
            end_period=4,
            teaching_class_id=3,
            course_name_snapshot="高等数学A",
            classroom_snapshot="教103",
            expected_count_snapshot=1,
            expected_count_current=1,
            roster_version=1,
        )
        # Task 4: 已取消任务
        task4 = InspectionTask(
            id=4,
            college_id=1,
            task_key="TASK-4",
            semester_id=1,
            inspection_date=date(2026, 10, 21),
            week_no=8,
            inspection_type=InspectionType.COURSE.value,
            start_period=5,
            end_period=6,
            teaching_class_id=1,
            course_name_snapshot="高等数学A",
            classroom_snapshot="教101",
            expected_count_snapshot=1,
            expected_count_current=1,
            roster_version=1,
            canceled_at=datetime(2026, 10, 21, 8, 0, 0),
            cancel_reason="教师请假",
        )
        db.add_all([task1, task2, task3, task4])
        db.flush()

        # 名单快照
        db.add_all([
            TaskRosterMember(
                task_id=1,
                roster_version=1,
                student_id=1,
                student_no="S001",
                name="张三",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计算机1班",
            ),
            TaskRosterMember(
                task_id=1,
                roster_version=1,
                student_id=2,
                student_no="S002",
                name="李四",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计算机1班",
            ),
            TaskRosterMember(
                task_id=1,
                roster_version=1,
                student_id=3,
                student_no="S003",
                name="王五",
                administrative_class_id_snapshot=2,
                class_name_snapshot="软件2班",
            ),
            TaskRosterMember(
                task_id=2,
                roster_version=1,
                student_id=4,
                student_no="S004",
                name="赵六",
                administrative_class_id_snapshot=3,
                class_name_snapshot="外院3班",
            ),
            TaskRosterMember(
                task_id=3,
                roster_version=1,
                student_id=1,
                student_no="S001",
                name="张三",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计算机1班",
            ),
            TaskRosterMember(
                task_id=4,
                roster_version=1,
                student_id=1,
                student_no="S001",
                name="张三",
                administrative_class_id_snapshot=1,
                class_name_snapshot="计算机1班",
            ),
        ])

        # 5. 考勤记录 (Task 1 和 Task 2 形成正式考勤)
        db.add_all([
            AttendanceRecord(task_id=1, student_id=1, effective_type="NORMAL", current_version=1),
            AttendanceRecord(task_id=1, student_id=2, effective_type="ABSENT", current_version=1),
            AttendanceRecord(task_id=1, student_id=3, effective_type="LEAVE", current_version=1),
            AttendanceRecord(task_id=2, student_id=4, effective_type="NORMAL", current_version=1),
        ])
        db.commit()
        yield db
    engine.dispose()


def _teacher_actor() -> CurrentUser:
    return CurrentUser(
        id=10,
        username="teacher",
        display_name="李老师",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )


def _counselor_actor() -> CurrentUser:
    return CurrentUser(
        id=20,
        username="counselor",
        display_name="王辅导员",
        status="ACTIVE",
        roles=[],  # 本轮不增设 STAFF 角色：纯教工在既有学生语义下是 pre_binding 受限会话
        permissions=[],
        pre_binding=True,
    )


def _stranger_actor() -> CurrentUser:
    return CurrentUser(
        id=30,
        username="stranger",
        display_name="路人",
        status="ACTIVE",
        roles=["STUDENT"],
        permissions=[],
        pre_binding=False,
    )


def test_teaching_view_local_anchor_does_not_expand_to_shared_views(staff_records_db):
    """LOCAL 不扩散到其他共享视图；SHARED 只扩展已确认映射。"""
    db = staff_records_db
    # 初始：给李老师赋予 TC1 的 LOCAL 授课关系
    assign = TeachingStaffAssignment(
        staff_id=101,
        semester_id=1,
        anchor_type="LOCAL",
        teaching_class_id=1,
        effective_from=date(2026, 9, 1),
    )
    db.add(assign)
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _teacher_actor

    with TestClient(app) as client:
        # 1. 列表：LOCAL 仅能看到学院1的 Task 1，看不到学院2的 Task 2
        res = client.get("/api/v1/me/inspection-records?view=teaching")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        task_ids = [item["task_id"] for item in data["items"]]
        assert "1" in task_ids
        assert "2" not in task_ids

        # 2. 单条详情读取：Task 1 允许，Task 2 拒绝 (404)
        assert client.get("/api/v1/me/inspection-records/1?view=teaching").status_code == 200
        assert client.get("/api/v1/me/inspection-records/2?view=teaching").status_code == 404

        # 3. 将授课关系改为 SHARED
        assign.anchor_type = "SHARED"
        assign.teaching_class_id = None
        assign.academic_offering_id = "shared-math"
        db.commit()

        # SHARED 扩展到已确认映射的 TC1 和 TC2
        res2 = client.get("/api/v1/me/inspection-records?view=teaching")
        assert res2.status_code == 200
        data2 = res2.json()["data"]
        task_ids2 = [item["task_id"] for item in data2["items"]]
        assert "1" in task_ids2
        assert "2" in task_ids2
        assert client.get("/api/v1/me/inspection-records/2?view=teaching").status_code == 200


def test_responsible_view_student_subset_consistency_and_no_leakage(staff_records_db):
    """责任班级子集统计/明细/导出一致，不泄露同任务其他学生。"""
    db = staff_records_db
    # 王辅导员仅负责计算机1班 (class_id=1)
    resp = ClassStaffResponsibility(
        staff_id=102,
        administrative_class_id=1,
        duty="COUNSELOR",
        effective_from=date(2026, 9, 1),
    )
    db.add(resp)
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _counselor_actor

    with TestClient(app) as client:
        # 1. 列表卡片：Task 1 包含班级1（张三、李四）和班级2（王五）
        # 辅导员只负责班级1，卡片统计 counts 必须且仅包含班级1的学生！
        res = client.get("/api/v1/me/inspection-records?view=responsible")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["total"] >= 1
        card1 = next(item for item in data["items"] if item["task_id"] == "1")
        assert card1["scope"]["view"] == "responsible"
        assert card1["scope"]["count_basis"] == "AUTHORIZED_STUDENT_SET"
        # 班级1学生：张三 NORMAL，李四 ABSENT。王五 LEAVE 绝不计入！
        assert card1["counts"]["total"] == 2
        assert card1["counts"]["NORMAL"] == 1
        assert card1["counts"]["ABSENT"] == 1
        assert card1["counts"]["LEAVE"] == 0

        # 2. 单条详情：counts 同样仅为 2
        detail = client.get("/api/v1/me/inspection-records/1?view=responsible").json()["data"]
        assert detail["counts"]["total"] == 2
        assert detail["counts"]["NORMAL"] == 1
        assert detail["counts"]["ABSENT"] == 1

        # 3. 考勤子列表：仅返回张三和李四，王五绝不泄漏！
        att_res = client.get("/api/v1/me/inspection-records/1/attendance?view=responsible")
        assert att_res.status_code == 200
        att_data = att_res.json()["data"]
        assert att_data["total"] == 2
        student_nos = [s["student_no"] for s in att_data["items"]]
        assert set(student_nos) == {"S001", "S002"}
        assert "S003" not in student_nos

        # 4. 同范围统计 summary：仅统计负责学生
        sum_res = client.get("/api/v1/me/inspection-records/summary?view=responsible")
        assert sum_res.status_code == 200
        sum_data = sum_res.json()["data"]
        assert sum_data["student_counts"]["total"] == 2
        assert sum_data["student_counts"]["NORMAL"] == 1
        assert sum_data["student_counts"]["ABSENT"] == 1
        assert sum_data["student_counts"]["LEAVE"] == 0

        # 5. 导出 Excel：验证导出行只含负责班级学生
        exp_res = client.get("/api/v1/me/inspection-records/export?view=responsible")
        assert exp_res.status_code == 200
        wb = openpyxl.load_workbook(BytesIO(exp_res.content))
        ws = wb.active
        exported_student_nos = [row[8] for row in ws.iter_rows(values_only=True)][1:]
        assert set(exported_student_nos) == {"S001", "S002"}
        assert "S003" not in exported_student_nos


def test_unrecorded_and_canceled_tasks_counts_null(staff_records_db):
    """无正式考勤 counts=null；未查课不算缺勤；不同学院任务不合并判定。"""
    db = staff_records_db
    # 给李老师分配 TC1 和 TC3
    db.add_all([
        TeachingStaffAssignment(
            staff_id=101,
            semester_id=1,
            anchor_type="LOCAL",
            teaching_class_id=1,
            effective_from=date(2026, 9, 1),
        ),
        TeachingStaffAssignment(
            staff_id=101,
            semester_id=1,
            anchor_type="LOCAL",
            teaching_class_id=3,
            effective_from=date(2026, 9, 1),
        ),
    ])
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _teacher_actor

    with TestClient(app) as client:
        res = client.get("/api/v1/me/inspection-records?view=teaching")
        assert res.status_code == 200
        items = {item["task_id"]: item for item in res.json()["data"]["items"]}

        # Task 3: 未形成正式考勤 -> counts 必须为 null
        assert items["3"]["attendance_state"] in ("PENDING_SUBMISSION", "NOT_RECORDED")
        assert items["3"]["counts"] is None

        # Task 4: 已取消 -> attendance_state 为 CANCELED，counts 必须为 null，不计为缺勤
        assert items["4"]["attendance_state"] == "CANCELED"
        assert items["4"]["counts"] is None


def test_direct_access_unauthorized_and_revocation_rejects_immediately(staff_records_db):
    """直接访问无权 task/file/record 拒绝；撤权后下一次读取或签名拒绝。"""
    db = staff_records_db
    assign = TeachingStaffAssignment(
        staff_id=101,
        semester_id=1,
        anchor_type="LOCAL",
        teaching_class_id=1,
        effective_from=date(2026, 9, 1),
    )
    db.add(assign)
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    # 1. 无教工档案的普通用户访问被拒绝 (403)
    app.dependency_overrides[get_current_user] = _stranger_actor
    with TestClient(app) as client:
        res = client.get("/api/v1/me/inspection-records?view=teaching")
        assert res.status_code == 403

    # 2. 缺少 view 参数返回 422
    app.dependency_overrides[get_current_user] = _teacher_actor
    with TestClient(app) as client:
        assert client.get("/api/v1/me/inspection-records").status_code == 422
        # 当前有权访问 Task 1
        assert client.get("/api/v1/me/inspection-records/1?view=teaching").status_code == 200

    # 3. 撤权：将授课关系置为已过期
    assign.effective_to = date(2026, 9, 15)
    db.commit()

    # 下一次请求立即拒绝访问 (404)
    with TestClient(app) as client:
        assert client.get("/api/v1/me/inspection-records/1?view=teaching").status_code == 404
        att_res = client.get("/api/v1/me/inspection-records/1/attendance?view=teaching")
        assert att_res.status_code == 404
        list_res = client.get("/api/v1/me/inspection-records?view=teaching").json()["data"]
        assert list_res["items"] == []
