"""学院注册、教师固定归属和本院负责人功能配置。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, PermissionDeniedError
from app.modules.academic.enrollment_models import (
    College,
    StudentManagerAppointment,
    TeacherCollegeBinding,
)
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.audit.models import AuditLog
from app.modules.identity.authorization import (
    business_today,
    require_student_scope,
    resolve_scope,
)
from app.modules.identity.models import UserAccount
from app.modules.identity.policy import MANAGER_FUNCTION_CODES
from app.modules.identity.repository import IdentityRepository
from app.modules.organization.models import School


class CollegeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IdentityRepository(db)

    @staticmethod
    def view(college: College) -> dict:
        return {
            "id": str(college.id),
            "code": college.code,
            "name": college.name,
            "status": college.status,
            "lock_version": college.lock_version,
        }

    def list(self, actor_id: int) -> list[dict]:
        scope = resolve_scope(self.db, actor_id, "academic.read")
        stmt = select(College).order_by(College.code)
        if scope.kind != "SCHOOL":
            stmt = stmt.where(College.id == scope.college_id)
        return [self.view(c) for c in self.db.scalars(stmt)]

    def create(self, actor_id: int, code: str, name: str, *, request_id: str | None) -> dict:
        self.db.rollback()
        if resolve_scope(self.db, actor_id, "system.config.manage").kind != "SCHOOL":
            raise PermissionDeniedError("仅管理员维护学院")
        if self.db.scalar(
            select(College.id).where((College.code == code) | (College.name == name))
        ):
            raise ConflictError(message="学院代码或名称已存在")
        school = self.db.scalar(select(School).limit(1))
        if school is None:
            raise ConflictError(message="请先配置学校")
        college = College(school_id=school.id, code=code, name=name)
        self.db.add(college)
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="academic.college.create",
                resource_type="college",
                resource_id=str(college.id),
                after_json=self.view(college),
                request_id=request_id,
            )
        )
        self.db.commit()
        return self.view(college)

    def teacher_college(self, actor_id: int, user_id: int) -> dict:
        roles = set(self.repo.list_role_codes(actor_id))
        if actor_id != user_id and "SUPER_ADMIN" not in roles:
            raise PermissionDeniedError()
        if actor_id != user_id:
            resolve_scope(self.db, actor_id, "account.read")
        user = self.db.get(UserAccount, user_id, populate_existing=True)
        if user is None:
            raise NotFoundError("账号不存在")
        binding = self.db.get(TeacherCollegeBinding, user_id)
        from app.modules.volunteer.models import VolunteerGroup

        groups = list(
            self.db.scalars(
                select(VolunteerGroup.id).where(
                    VolunteerGroup.owner_user_id == user_id, VolunteerGroup.status != "INACTIVE"
                )
            )
        )
        return {
            "user_id": str(user.id),
            "college_id": str(binding.college_id) if binding else None,
            "lock_version": user.lock_version,
            "handoff": {
                "active_owned_group_ids": [str(gid) for gid in groups],
                "resource_policy": "KEEP_OLD_COLLEGE",
                "group_reassignment": "ADMIN_REQUIRED",
            },
        }

    def set_teacher_college(
        self,
        actor_id: int,
        user_id: int,
        college_id: int,
        expected_version: int,
        *,
        request_id: str | None,
    ) -> dict:
        self.db.rollback()
        for uid in sorted({actor_id, user_id}):
            self.repo.get_user_by_id_for_update(uid)
        if resolve_scope(self.db, actor_id, "account.manage").kind != "SCHOOL":
            raise PermissionDeniedError("教师归属仅由管理员维护")
        user = self.db.get(UserAccount, user_id)
        roles = set(self.repo.list_role_codes(user_id))
        if user is None or "TEACHER_ADMIN" not in roles or "SUPER_ADMIN" in roles:
            raise NotFoundError("教师账号不存在")
        if user.lock_version != expected_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT)
        college = self.db.get(College, college_id)
        if college is None or college.status != "ACTIVE":
            raise NotFoundError("学院不存在或已停用")
        binding = self.db.get(TeacherCollegeBinding, user_id)
        before = str(binding.college_id) if binding else None
        if binding:
            old_college = self.db.get(College, binding.college_id)
            if old_college:
                old_college.authorization_revision += 1
        if binding:
            binding.college_id = college_id
            binding.lock_version += 1
        else:
            self.db.add(TeacherCollegeBinding(user_id=user_id, college_id=college_id))
        user.lock_version += 1
        college.authorization_revision += 1
        self.repo.revoke_active_sessions(user_id, utcnow())
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="account.teacher.college",
                resource_type="user_account",
                resource_id=str(user_id),
                before_json={"college_id": before},
                after_json={
                    "college_id": str(college_id),
                    "lock_version": user.lock_version,
                    "resource_ownership_policy": "KEEP_OLD_COLLEGE",
                    "sessions": "REVOKED",
                },
                request_id=request_id,
            )
        )
        self.db.commit()
        return self.teacher_college(actor_id, user_id)

    def manager_functions(self, actor_id: int, user_id: int) -> dict:
        user = self.db.get(UserAccount, user_id, populate_existing=True)
        if (
            user is None
            or user.student_id is None
            or "STUDENT_AFFAIRS_MANAGER" not in self.repo.list_role_codes(user_id)
        ):
            raise NotFoundError("有效学生负责人不存在")
        require_student_scope(self.db, actor_id, "optional_permission.manage", user.student_id)
        today = business_today()
        appointment = self.db.scalar(
            select(StudentManagerAppointment)
            .where(
                StudentManagerAppointment.user_id == user_id,
                StudentManagerAppointment.effective_from <= today,
                or_(
                    StudentManagerAppointment.effective_to.is_(None),
                    StudentManagerAppointment.effective_to > today,
                ),
            )
            .order_by(StudentManagerAppointment.id.desc())
            .limit(1)
        )
        enrollment = EnrollmentService(self.db).at(user.student_id, today)
        if (
            appointment is None
            or enrollment is None
            or enrollment.status != "ENROLLED"
            or appointment.college_id != enrollment.college_id
        ):
            raise ConflictError(message="任命与本人当前学院不一致，请重新委任")
        return {
            "user_id": str(user_id),
            "college_id": str(appointment.college_id),
            "appointment_id": str(appointment.id),
            "allowed_actions": appointment.allowed_actions,
            "configurable_actions": sorted(MANAGER_FUNCTION_CODES),
            "lock_version": user.lock_version,
        }

    def set_manager_functions(
        self,
        actor_id: int,
        user_id: int,
        actions: Sequence[str],
        expected_version: int,
        *,
        request_id: str | None,
    ) -> dict:
        self.db.rollback()
        for uid in sorted({actor_id, user_id}):
            self.repo.get_user_by_id_for_update(uid)
        if actor_id == user_id:
            raise PermissionDeniedError("不能为自己配置管理功能")
        before = self.manager_functions(actor_id, user_id)
        if not set(actions) <= MANAGER_FUNCTION_CODES:
            raise PermissionDeniedError("负责人功能不能包含学籍、账号或校级设置")
        user = self.db.get(UserAccount, user_id)
        if user is None or user.lock_version != expected_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT)
        appointment = self.db.get(StudentManagerAppointment, int(before["appointment_id"]))
        if appointment is None:
            raise ConflictError(message="任命已变化")
        appointment.allowed_actions = sorted(set(actions))
        statistics = self.repo.get_permission_by_code("statistics.read")
        if statistics:
            if "statistics.read" in actions:
                self.repo.set_user_permission(user_id, statistics.id, actor_id)
            else:
                self.repo.revoke_user_permission(user_id, statistics.id)
        user.lock_version += 1
        college = self.db.get(College, appointment.college_id)
        if college:
            college.authorization_revision += 1
        self.repo.revoke_active_sessions(user_id, utcnow())
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action="account.manager.functions",
                resource_type="user_account",
                resource_id=str(user_id),
                before_json=before,
                after_json={
                    "allowed_actions": appointment.allowed_actions,
                    "college_id": str(appointment.college_id),
                    "lock_version": user.lock_version,
                },
                request_id=request_id,
            )
        )
        self.db.commit()
        return self.manager_functions(actor_id, user_id)
