"""固定学院范围；空绑定不能产生全校权限。"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
from app.modules.academic.enrollment_models import College, TeacherCollegeBinding
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository


def business_today() -> date:
    return (utcnow() + timedelta(hours=get_settings().app_utc_offset_hours)).date()


def active_manager_appointment(db: Session, user_id: int, today: date):
    from sqlalchemy import or_, select

    from app.modules.academic.enrollment_models import StudentManagerAppointment
    from app.modules.academic.enrollment_service import EnrollmentService

    user = db.get(UserAccount, user_id)
    e = (
        EnrollmentService(db).at(user.student_id, today)
        if user and user.is_active and user.student_id
        else None
    )
    if e is None or e.status != "ENROLLED":
        return None
    return db.scalar(
        select(StudentManagerAppointment)
        .where(
            StudentManagerAppointment.user_id == user_id,
            StudentManagerAppointment.college_id == e.college_id,
            StudentManagerAppointment.effective_from <= today,
            or_(
                StudentManagerAppointment.effective_to.is_(None),
                StudentManagerAppointment.effective_to > today,
            ),
        )
        .order_by(StudentManagerAppointment.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class ResourceScope:
    kind: Literal["SCHOOL", "COLLEGE", "SELF"]
    college_id: int | None = None
    student_id: int | None = None


def resolve_scope(session: Session, actor_id: int, action: str) -> ResourceScope:
    from app.modules.identity.query_scope import activate_query_scope

    if session.info.get("query_scope_actor_id") != actor_id:
        activate_query_scope(session, actor_id)
    repo = IdentityRepository(session)
    user = repo.get_user_by_id_for_update(actor_id)
    from app.modules.identity.query_scope import recheck_query_scope

    recheck_query_scope(session, actor_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("操作者账号不可用")
    roles = set(repo.list_role_codes(actor_id))
    if action not in repo.list_effective_permissions(actor_id):
        raise PermissionDeniedError("无此操作权限")
    if "SUPER_ADMIN" in roles:
        return ResourceScope("SCHOOL")
    if "TEACHER_ADMIN" in roles:
        binding = session.get(TeacherCollegeBinding, actor_id, populate_existing=True)
        college = session.get(College, binding.college_id) if binding else None
        if college is None or (college.status != "ACTIVE" and not action.endswith(".read")):
            raise PermissionDeniedError("教师尚未配置有效学院归属")
        return ResourceScope("COLLEGE", college.id)
    if "STUDENT_AFFAIRS_MANAGER" in roles:
        if action == "student.manage":
            raise PermissionDeniedError("学生负责人不能办理学籍异动或归档")
        from sqlalchemy import or_, select

        from app.modules.academic.enrollment_models import StudentManagerAppointment
        from app.modules.academic.enrollment_service import EnrollmentService

        today = business_today()
        enrollment = (
            EnrollmentService(session).at(user.student_id, today) if user.student_id else None
        )
        appointment = session.scalar(
            select(StudentManagerAppointment)
            .where(
                StudentManagerAppointment.user_id == actor_id,
                StudentManagerAppointment.effective_from <= today,
                or_(
                    StudentManagerAppointment.effective_to.is_(None),
                    StudentManagerAppointment.effective_to > today,
                ),
            )
            .order_by(StudentManagerAppointment.id.desc())
            .limit(1)
        )
        if (
            enrollment is None
            or enrollment.status != "ENROLLED"
            or appointment is None
            or enrollment.college_id != appointment.college_id
            or action not in appointment.allowed_actions
        ):
            raise PermissionDeniedError("负责人任命不在本人当前学院或此功能未开启")
        return ResourceScope("COLLEGE", appointment.college_id, user.student_id)
    return ResourceScope("SELF", student_id=user.student_id)


def require_resource_scope(scope: ResourceScope, college_id: int | None) -> None:
    if scope.kind == "SCHOOL":
        return
    if scope.kind != "COLLEGE" or college_id is None or scope.college_id != college_id:
        raise PermissionDeniedError("资源不在本学院工作区")


def current_student_college(session: Session, student: Student) -> int | None:
    from app.modules.academic.enrollment_service import EnrollmentService

    enrollment = EnrollmentService(session).at(student.id, business_today())
    if enrollment is not None:
        return enrollment.college_id
    ac = (
        session.get(AdministrativeClass, student.administrative_class_id)
        if student.administrative_class_id
        else None
    )
    return ac.college_id if ac else None


def require_student_scope(
    session: Session, actor_id: int, action: str, student_id: int
) -> ResourceScope:
    scope = resolve_scope(session, actor_id, action)
    student = session.get(Student, student_id, populate_existing=True)
    if student is None:
        raise PermissionDeniedError("学生不在可管理范围")
    require_resource_scope(scope, current_student_college(session, student))
    return scope


ACADEMIC_SCOPE_ACTIONS = frozenset(
    {"academic.read", "academic.manage", "student.read", "student.manage", "volunteer.read"}
)

CAMPUS_ACTIONS = ACADEMIC_SCOPE_ACTIONS | frozenset(
    {
        "academic.course_type.read",
        "academic.course_type.manage",
        "volunteer.group.read",
        "volunteer.group.manage",
        "volunteer.member.manage",
        "volunteer.config.publish",
    }
)

CAMPUS_PERMISSION_ACTION = {
    "academic.course_type.read": "academic.read",
    "academic.course_type.manage": "academic.manage",
    "volunteer.group.read": "volunteer.read",
    "volunteer.group.manage": "volunteer.manage",
    "volunteer.member.manage": "volunteer.manage",
    "volunteer.config.publish": "volunteer.manage",
}


def fixed_college_actions(session: Session, actor_id: int, college_id: int) -> frozenset[str]:
    """旧 ScopedGrant 不再产生有效能力；角色及唯一归属决定范围。"""
    from sqlalchemy import or_, select

    from app.modules.academic.enrollment_models import StudentManagerAppointment
    from app.modules.academic.enrollment_service import EnrollmentService
    from app.modules.identity.policy import DEFAULT_ROLE_PERMISSIONS

    repo = IdentityRepository(session)
    user = repo.get_user_by_id(actor_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError()
    roles = set(repo.list_role_codes(actor_id))
    if "SUPER_ADMIN" in roles:
        return CAMPUS_ACTIONS | frozenset(repo.list_effective_permissions(actor_id))
    if "TEACHER_ADMIN" in roles:
        binding = session.get(TeacherCollegeBinding, actor_id, populate_existing=True)
        if binding is not None and binding.college_id == college_id:
            return CAMPUS_ACTIONS | DEFAULT_ROLE_PERMISSIONS["TEACHER_ADMIN"]
        return frozenset()
    if "STUDENT_AFFAIRS_MANAGER" in roles and user.student_id is not None:
        today = business_today()
        e = EnrollmentService(session).at(user.student_id, today)
        if e is None or e.status != "ENROLLED" or e.college_id != college_id:
            return frozenset()
        appointment = session.scalar(
            select(StudentManagerAppointment)
            .where(
                StudentManagerAppointment.user_id == actor_id,
                StudentManagerAppointment.college_id == college_id,
                StudentManagerAppointment.effective_from <= today,
                or_(
                    StudentManagerAppointment.effective_to.is_(None),
                    StudentManagerAppointment.effective_to > today,
                ),
            )
            .order_by(StudentManagerAppointment.id.desc())
            .limit(1)
        )
        if appointment:
            permitted = frozenset(repo.list_effective_permissions(actor_id))
            return permitted | frozenset(
                a for a in CAMPUS_ACTIONS if CAMPUS_PERMISSION_ACTION.get(a, a) in permitted
            )
    return frozenset()


def effective_actions(grants, college_id: int, now) -> frozenset[str]:
    return frozenset(
        action
        for grant in grants
        if grant.college_id == college_id
        and grant.status == "ACTIVE"
        and (grant.starts_at is None or grant.starts_at <= now)
        and (grant.expires_at is None or grant.expires_at > now)
        for action in grant.actions
        if action in CAMPUS_ACTIONS
    )
