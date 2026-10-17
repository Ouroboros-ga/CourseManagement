"""教职工档案与任职管理的定向回归；仅使用独立内存库，不触碰运行库。

覆盖 T01 验收：工号唯一性与前导零、同名不合并、同班多教师与同职责重叠、
交接日半开区间生效、版本乐观并发，以及普通教工够不到学院管理范围。
"""

from datetime import date

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.academic.models import AdministrativeClass, Course, Semester, TeachingClass
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_service import StaffManagementService
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_scope import responsible_class_condition
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def staff_env():
    from app import models  # noqa: F401  # ORM 聚合入口，确保全部表已注册
    from app.core.database import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all(
            [
                College(id=1, school_id=1, code="A", name="甲院"),
                College(id=2, school_id=1, code="B", name="乙院"),
            ]
        )
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
        db.add_all(
            [
                Course(id=1, college_id=1, course_code="M", course_name="数学"),
                Course(id=2, college_id=2, course_code="M", course_name="数学"),
            ]
        )
        db.flush()
        db.add_all(
            [
                TeachingClass(
                    id=1,
                    college_id=1,
                    semester_id=1,
                    course_id=1,
                    class_code="T1",
                    class_name="数学1班",
                    academic_offering_id="shared",
                ),
                TeachingClass(
                    id=2,
                    college_id=2,
                    semester_id=1,
                    course_id=2,
                    class_code="T2",
                    class_name="数学2班",
                    academic_offering_id="shared",
                ),
            ]
        )
        db.add_all(
            [
                AdministrativeClass(id=1, college_id=1, class_code="A1", class_name="一班"),
                AdministrativeClass(id=2, college_id=2, class_code="B1", class_name="二班"),
            ]
        )
        admin = UserAccount(id=1, display_name="超管", status="ACTIVE")
        teacher = UserAccount(id=2, display_name="本院管理员", status="ACTIVE")
        wechat = UserAccount(id=3, display_name="微信教工", status="ACTIVE")
        student_staff = UserAccount(id=4, display_name="学生兼教工", status="ACTIVE")
        db.add_all([admin, teacher, wechat, student_staff])
        db.flush()
        super_role = Role(code="SUPER_ADMIN", name="超级管理员")
        teacher_role = Role(code="TEACHER_ADMIN", name="教师管理员")
        student_role = Role(code="STUDENT", name="学生")
        db.add_all([super_role, teacher_role, student_role])
        db.flush()
        db.add_all(
            [
                UserRole(user_id=admin.id, role_id=super_role.id),
                UserRole(user_id=teacher.id, role_id=teacher_role.id),
                UserRole(user_id=student_staff.id, role_id=student_role.id),
            ]
        )
        db.add(TeacherCollegeBinding(user_id=teacher.id, college_id=1))
        db.commit()
        yield {
            "db": db,
            "admin": CurrentUser(admin.id, None, "超管", "ACTIVE", ["SUPER_ADMIN"], []),
            "teacher": CurrentUser(
                teacher.id, None, "本院管理员", "ACTIVE", ["TEACHER_ADMIN"], ["academic.manage"]
            ),
            "plain": CurrentUser(wechat.id, None, "微信教工", "ACTIVE", [], [], pre_binding=True),
            "student_staff": CurrentUser(
                student_staff.id, None, "学生兼教工", "ACTIVE", ["STUDENT"], ["attendance.read"]
            ),
            "accounts": {"admin": admin, "teacher": teacher, "wechat": wechat},
        }
    engine.dispose()


def service(env, actor=None, college_id=1):
    return StaffManagementService(env["db"], actor or env["admin"], college_id)


def create_staff(env, staff_no, name="教师", actor=None, college_id=1):
    return service(env, actor, college_id).create_staff({"staff_no": staff_no, "name": name})


def link(env, row, account):
    return service(env).link_account(
        int(row["id"]), {"user_id": str(account.id), "lock_version": row["lock_version"]}
    )


def page():
    return PageParams(page=1, page_size=50)


def audit_rows(env, action):
    return list(
        env["db"].scalars(
            select(AuditLog).where(
                AuditLog.action == action, AuditLog.resource_type == kind_of(action)
            )
        )
    )


def kind_of(action):
    return {
        "staff.create": "faculty_staff",
        "staff.update": "faculty_staff",
        "staff.account_link": "faculty_staff",
        "teaching_assignment.create": "teaching_staff_assignment",
        "responsibility.create": "class_staff_responsibility",
        "responsibility.handover": "class_staff_responsibility",
    }[action]


def visible_classes(env, user_id, as_of):
    return sorted(
        env["db"].scalars(
            select(AdministrativeClass.id).where(
                responsible_class_condition(
                    user_id, administrative_class_id=AdministrativeClass.id, as_of=as_of
                )
            )
        )
    )


def test_staff_number_keeps_leading_zeros_and_is_unique_per_school(staff_env):
    created = create_staff(staff_env, "00001", "张老师")
    assert created["staff_no"] == "00001"
    assert created["status"] == "ACTIVE"
    assert created["lock_version"] == 1

    with pytest.raises(ConflictError):
        create_staff(staff_env, "00001", "同名不同人")
    # 工号唯一性锚定学校，换一个学院工作区同样不能重复。
    with pytest.raises(ConflictError):
        create_staff(staff_env, "00001", "跨院重复", college_id=2)

    listed = service(staff_env).list_staff(page())
    assert [row["staff_no"] for row in listed["items"]] == ["00001"]
    assert listed["total"] == 1


def test_same_name_different_number_stays_two_profiles(staff_env):
    first = create_staff(staff_env, "00001", "同名")
    second = create_staff(staff_env, "00002", "同名")
    assert first["id"] != second["id"]

    linked = link(staff_env, first, staff_env["accounts"]["wechat"])
    assert linked["user_id"] == str(staff_env["accounts"]["wechat"].id)
    # 姓名相同不构成关联依据：另一份档案仍然无人。
    assert service(staff_env).get_staff(int(second["id"]))["user_id"] is None


def test_archive_update_requires_current_version_and_is_audited(staff_env):
    created = create_staff(staff_env, "00001")
    staff_id = int(created["id"])
    with pytest.raises(ConflictError):
        service(staff_env).update_staff(staff_id, {"lock_version": 5, "phone": "13800000000"})
    updated = service(staff_env).update_staff(
        staff_id,
        {"lock_version": 1, "phone": "13800000000", "status": "INACTIVE", "reason": "离职"},
    )
    assert updated["phone"] == "13800000000"
    assert updated["status"] == "INACTIVE"
    assert updated["lock_version"] == 2
    assert len(audit_rows(staff_env, "staff.update")) == 1


def test_two_teachers_share_a_class_but_duplicate_appointment_is_rejected(staff_env):
    staff_service = service(staff_env)
    first = create_staff(staff_env, "T1")
    second = create_staff(staff_env, "T2")
    payload = {
        "semester_id": "1",
        "anchor_type": "LOCAL",
        "teaching_class_id": "1",
        "effective_from": "2026-09-01",
    }
    for row in (first, second):
        staff_service.create_teaching_assignment({**payload, "staff_id": row["id"]})
    assert len(staff_service.list_teaching_assignments()) == 2

    with pytest.raises(ConflictError):
        staff_service.create_teaching_assignment(
            {**payload, "staff_id": first["id"], "effective_from": "2026-10-01"}
        )
    # 半开区间不含结束日：上一段在 2026-10-01 结束后可以重新任命。
    ended = staff_service.end_teaching_assignment(
        int(staff_service.list_teaching_assignments(staff_id=int(first["id"]))[0]["id"]),
        {"effective_to": "2026-10-01", "lock_version": 1},
    )
    assert ended["effective_to"] == "2026-10-01"
    staff_service.create_teaching_assignment(
        {**payload, "staff_id": first["id"], "effective_from": "2026-10-01"}
    )


def test_local_and_shared_anchor_over_the_same_resource_are_refused(staff_env):
    staff_service = service(staff_env)
    teacher = create_staff(staff_env, "T1")
    staff_service.create_teaching_assignment(
        {
            "staff_id": teacher["id"],
            "semester_id": "1",
            "anchor_type": "LOCAL",
            "teaching_class_id": "1",
            "effective_from": "2026-09-01",
        }
    )
    with pytest.raises(ConflictError):
        staff_service.create_teaching_assignment(
            {
                "staff_id": teacher["id"],
                "semester_id": "1",
                "anchor_type": "SHARED",
                "academic_offering_id": "shared",
                "effective_from": "2026-09-15",
            }
        )


def test_teaching_assignment_requires_a_live_target(staff_env):
    staff_service = service(staff_env)
    teacher = create_staff(staff_env, "T1")
    payload = {
        "staff_id": teacher["id"],
        "semester_id": "1",
        "anchor_type": "LOCAL",
        "effective_from": "2026-09-01",
    }
    # 外院教学班不在本学院工作区。
    with pytest.raises(NotFoundError):
        staff_service.create_teaching_assignment({**payload, "teaching_class_id": "2"})
    staff_service.create_teaching_assignment({**payload, "teaching_class_id": "1"})
    # 已停用档案不能再被任命。
    staff_service.update_staff(int(teacher["id"]), {"lock_version": 1, "status": "INACTIVE"})
    with pytest.raises(ConflictError):
        staff_service.create_teaching_assignment(
            {
                "staff_id": teacher["id"],
                "semester_id": "1",
                "anchor_type": "SHARED",
                "academic_offering_id": "shared",
                "effective_from": "2027-02-01",
            }
        )


def test_responsibility_overlap_is_refused_while_other_duty_is_allowed(staff_env):
    staff_service = service(staff_env)
    head = create_staff(staff_env, "R1")
    counselor = create_staff(staff_env, "R2")
    staff_service.create_responsibility(
        {
            "staff_id": head["id"],
            "administrative_class_id": "1",
            "duty": "HEAD_TEACHER",
            "effective_from": "2026-09-01",
        }
    )
    with pytest.raises(ConflictError):
        staff_service.create_responsibility(
            {
                "staff_id": counselor["id"],
                "administrative_class_id": "1",
                "duty": "HEAD_TEACHER",
                "effective_from": "2026-09-20",
            }
        )
    staff_service.create_responsibility(
        {
            "staff_id": counselor["id"],
            "administrative_class_id": "1",
            "duty": "COUNSELOR",
            "effective_from": "2026-09-01",
        }
    )
    assert len(staff_service.list_responsibilities()) == 2
    # 责任关系必须落在档案所属学院的行政班内。
    with pytest.raises(NotFoundError):
        staff_service.create_responsibility(
            {
                "staff_id": head["id"],
                "administrative_class_id": "2",
                "duty": "COUNSELOR",
                "effective_from": "2026-09-01",
            }
        )


def test_handover_makes_the_old_relation_inactive_on_the_handover_date(staff_env):
    staff_service = service(staff_env)
    leaving = create_staff(staff_env, "R1")
    successor = create_staff(staff_env, "R2")
    link(staff_env, leaving, staff_env["accounts"]["wechat"])
    link(staff_env, successor, staff_env["accounts"]["teacher"])
    created = staff_service.create_responsibility(
        {
            "staff_id": leaving["id"],
            "administrative_class_id": "1",
            "duty": "HEAD_TEACHER",
            "effective_from": "2026-09-01",
        }
    )
    with pytest.raises(ConflictError):
        staff_service.handover_responsibility(
            int(created["id"]),
            {
                "successor_staff_id": successor["id"],
                "effective_on": "2026-10-20",
                "lock_version": 9,
            },
        )

    result = staff_service.handover_responsibility(
        int(created["id"]),
        {
            "successor_staff_id": successor["id"],
            "effective_on": "2026-10-20",
            "lock_version": 1,
        },
    )
    assert result["ended"]["effective_to"] == "2026-10-20"
    assert result["created"]["effective_from"] == "2026-10-20"
    assert result["created"]["duty"] == "HEAD_TEACHER"

    leaving_user = staff_env["accounts"]["wechat"].id
    successor_user = staff_env["accounts"]["teacher"].id
    assert visible_classes(staff_env, leaving_user, date(2026, 10, 19)) == [1]
    # 交接日当天旧关系不再有效，新关系自当日生效。
    assert visible_classes(staff_env, leaving_user, date(2026, 10, 20)) == []
    assert visible_classes(staff_env, successor_user, date(2026, 10, 20)) == [1]
    current = staff_service.list_responsibilities(
        administrative_class_id=1, as_of=date(2026, 10, 20)
    )
    assert [(row["duty"], row["effective_from"]) for row in current] == [
        ("HEAD_TEACHER", "2026-10-20")
    ]
    assert len(audit_rows(staff_env, "responsibility.handover")) == 1


def test_plain_staff_and_student_accounts_cannot_reach_college_scope(staff_env):
    from app.modules.identity.deps import require_binding_complete

    with pytest.raises(PermissionDeniedError):
        service(staff_env, staff_env["plain"]).list_staff(page())
    with pytest.raises(PermissionDeniedError):
        require_binding_complete(staff_env["plain"])
    # 已绑学生的教工同样没有学院管理范围，只按固定身份判定。
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        service(staff_env, staff_env["student_staff"]).list_staff(page())


def test_teacher_admin_scope_is_limited_to_the_own_college(staff_env):
    teacher_service = service(staff_env, staff_env["teacher"], college_id=1)
    created = teacher_service.create_staff({"staff_no": "00001", "name": "本院教师"})
    assert created["college_id"] == "1"
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        service(staff_env, staff_env["teacher"], college_id=2).list_staff(page())
    with pytest.raises(NotFoundError):
        service(staff_env, staff_env["teacher"], college_id=2).get_staff(int(created["id"]))
