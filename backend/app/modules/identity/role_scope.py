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
        EnrollmentService(db).at(user.student_id, today, lock=True)
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
        .with_for_update(read=True)
    )


@dataclass(frozen=True)
class DefaultRoleScope:
    kind: Literal["SCHOOL", "COLLEGE", "SELF"]
    college_id: int | None = None
    student_id: int | None = None
    authorized_college_ids: frozenset[int] = frozenset()


def resolve_scope(session: Session, actor_id: int, action: str) -> DefaultRoleScope:
    repo = IdentityRepository(session)
    user = repo.get_user_by_id_for_update(actor_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("操作者账号不可用")
    roles = set(repo.list_role_codes(actor_id))
    if action not in repo.list_effective_permissions(actor_id):
        raise PermissionDeniedError("无此操作权限")
    if "SUPER_ADMIN" in roles:
        return DefaultRoleScope("SCHOOL")
    if "TEACHER_ADMIN" in roles:
        binding = session.get(TeacherCollegeBinding, actor_id, populate_existing=True)
        college = (
            session.get(College, binding.college_id, populate_existing=True) if binding else None
        )
        if college is None or college.status != "ACTIVE":
            raise PermissionDeniedError("教师尚未配置有效学院归属")
        from sqlalchemy import select

        from app.modules.organization.models import ScopedGrant

        now = utcnow()
        # 主学院保持唯一；跨院动作仅来自超管显式、有效且匹配当前动作的授权。
        active_colleges = select(College.id).where(College.status == "ACTIVE")
        grants = session.scalars(
            select(ScopedGrant)
            .where(
                ScopedGrant.user_id == actor_id,
                ScopedGrant.status == "ACTIVE",
                ScopedGrant.college_id.in_(active_colleges),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        authorized = frozenset(
            g.college_id
            for g in grants
            if action in g.actions
            and (g.starts_at is None or g.starts_at <= now)
            and (g.expires_at is None or g.expires_at > now)
        )
        return DefaultRoleScope("COLLEGE", college.id, authorized_college_ids=authorized)
    if "STUDENT_AFFAIRS_MANAGER" in roles:
        if action == "student.manage":
            raise PermissionDeniedError("学生负责人不能办理学籍异动或归档")
        from sqlalchemy import or_, select

        from app.modules.academic.enrollment_models import StudentManagerAppointment
        from app.modules.academic.enrollment_service import EnrollmentService

        today = business_today()
        enrollment = (
            EnrollmentService(session).at(user.student_id, today, lock=True)
            if user.student_id
            else None
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
        return DefaultRoleScope("COLLEGE", appointment.college_id, user.student_id)
    return DefaultRoleScope("SELF", student_id=user.student_id)


def require_resource_scope(scope: DefaultRoleScope, college_id: int | None) -> None:
    if scope.kind == "SCHOOL":
        return
    if (
        scope.kind != "COLLEGE"
        or college_id is None
        or (scope.college_id != college_id and college_id not in scope.authorized_college_ids)
    ):
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
) -> DefaultRoleScope:
    scope = resolve_scope(session, actor_id, action)
    student = session.get(Student, student_id, populate_existing=True)
    if student is None:
        raise PermissionDeniedError("学生不在可管理范围")
    require_resource_scope(scope, current_student_college(session, student))
    return scope
