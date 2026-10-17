"""Campus capability catalog; legacy role helpers delegate to one implementation."""

from sqlalchemy.orm import Session

from app.core.exceptions import UnauthenticatedError
from app.modules.academic.enrollment_models import College, TeacherCollegeBinding
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.role_scope import (
    DefaultRoleScope,
)
from app.modules.identity.role_scope import (
    active_manager_appointment as active_manager_appointment,
)
from app.modules.identity.role_scope import (
    business_today as business_today,
)
from app.modules.identity.role_scope import (
    current_student_college as current_student_college,
)
from app.modules.identity.role_scope import (
    require_resource_scope as require_resource_scope,
)
from app.modules.identity.role_scope import (
    require_student_scope as require_student_scope,
)
from app.modules.identity.role_scope import (
    resolve_scope as resolve_scope,
)

ResourceScope = DefaultRoleScope


ACADEMIC_SCOPE_ACTIONS = frozenset(
    {"academic.read", "academic.manage", "student.read", "student.manage", "volunteer.read"}
)

BUSINESS_SCOPE_ACTIONS = frozenset(
    {"import.execute", "course_schedule.import", "course_schedule.export", "volunteer.manage", "audit.read", "identity.binding.manage", "role.assign", "optional_permission.manage",
     "attendance.read", "attendance.correct", "objection.read", "objection.final_review",
     "submission.read", "submission.review", "inspection.read", "inspection.roster.read",
     "statistics.read", "report.read", "report.generate", "inspection.generate",
     "inspection.cancel", "assignment.manage", "assignment.change_review",
     "inspection.roster.manage", "attendance.expected_count_adjust",
     "submission_deadline.read", "submission_deadline.manage"}
)

# 教职工档案管理是显式院级能力：只由固定学院身份或明确 ScopedGrant 产生，
# 不映射到任何旧 Permission code，避免负责人或普通教工被间接提权。
STAFF_MANAGE_ACTION = "staff.manage"
STAFF_SCOPE_ACTIONS = frozenset({STAFF_MANAGE_ACTION})

CAMPUS_ACTIONS = (
    ACADEMIC_SCOPE_ACTIONS
    | BUSINESS_SCOPE_ACTIONS
    | STAFF_SCOPE_ACTIONS
    | frozenset(
        {
            "academic.course_type.read",
            "academic.course_type.manage",
            "volunteer.group.read",
            "volunteer.group.manage",
            "volunteer.member.manage",
            "volunteer.config.publish",
        }
    )
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
    """固定身份产生本院能力；跨院授权由调用方另按具体动作核验。"""
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
        college = session.get(College, college_id, populate_existing=True)
        if binding is not None and binding.college_id == college_id and college and college.status == "ACTIVE":
            return CAMPUS_ACTIONS | DEFAULT_ROLE_PERMISSIONS["TEACHER_ADMIN"]
        return frozenset()
    if "STUDENT_AFFAIRS_MANAGER" in roles and user.student_id is not None:
        today = business_today()
        e = EnrollmentService(session).at(user.student_id, today, lock=True)
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
            .with_for_update(read=True)
        )
        if appointment:
            permitted = frozenset(repo.list_effective_permissions(actor_id)) & frozenset(appointment.allowed_actions)
            return permitted | frozenset(
                a for a in CAMPUS_ACTIONS if CAMPUS_PERMISSION_ACTION.get(a, a) in permitted
            )
    return frozenset()


def effective_actions(grants, college_id: int, now, *, include_restricted=False) -> frozenset[str]:
    return frozenset(
        action
        for grant in grants
        if grant.college_id == college_id
        and grant.status == "ACTIVE"
        and (grant.starts_at is None or grant.starts_at <= now)
        and (grant.expires_at is None or grant.expires_at > now)
        and (include_restricted or not getattr(grant, "resource_scope", None)
             or grant.resource_scope.get("kind") == "COLLEGE")
        for action in grant.actions
        if action in CAMPUS_ACTIONS
    )
