"""教师账号生命周期；停用与改密同事务撤销会话，保留历史和审计。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, PermissionDeniedError
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password, verify_password
from app.modules.academic.models import Student
from app.modules.audit.models import AuditLog
from app.modules.identity.account_schemas import (
    AdministratorAccountCreate,
    AdministratorAccountUpdate,
    PasswordChange,
    PasswordReset,
    TeacherAccountCreate,
    TeacherAccountUpdate,
)
from app.modules.identity.models import (
    Permission,
    Role,
    UserAccount,
    UserPermission,
    UserRole,
    UserStatus,
)
from app.modules.identity.policy import can_manage_administrator
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser, IdentityService
from app.modules.organization.service import atomic_write


def lock_admin_registry(session: Session) -> None:
    """先锁稳定角色行，再锁账号；串行化最后超管的撤角色/停用检查。"""
    session.execute(
        select(Role.id).where(Role.code == RoleCode.SUPER_ADMIN.value).with_for_update()
    ).all()


def require_another_admin(session: Session, target_id: int) -> None:
    ids = (
        session.execute(
            select(UserAccount.id)
            .join(UserRole)
            .join(Role)
            .where(
                Role.code == RoleCode.SUPER_ADMIN.value,
                UserAccount.status == UserStatus.ACTIVE.value,
                UserAccount.id != target_id,
            )
            .order_by(UserAccount.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )
    if not ids:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "不能停用或撤销最后一个有效超级管理员")


def require_another_administrator_manager(session: Session, target_id: int) -> None:
    """调用者持稳定管理员注册行锁，避免并发撤空平台管理能力。"""
    ids = session.scalars(
        select(UserAccount.id)
        .join(UserRole, UserRole.user_id == UserAccount.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(UserPermission, UserPermission.user_id == UserAccount.id)
        .join(Permission, Permission.id == UserPermission.permission_id)
        .where(
            Role.code == "SUPER_ADMIN",
            Permission.code == "administrator_account.manage",
            UserAccount.status == "ACTIVE",
            UserAccount.id != target_id,
        )
        .order_by(UserAccount.id)
        .with_for_update()
    ).all()
    if not ids:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "不能撤销或停用最后一个有效平台管理者")


class AccountService:
    def __init__(self, session: Session):
        self.session = session
        self.db = session  # Shared atomic_write rollback protocol.
        self.repo = IdentityRepository(session)
        self.identity = IdentityService(session)

    def _school_summary_permission(self, actor, user, enabled):
        permission = self.repo.get_permission_by_code("statistics.school.read")
        if permission is None:
            raise ConflictError(message="请先同步全校汇总权限注册表")
        if enabled:
            self.repo.set_user_permission(user.id, permission.id, actor.id)
        else:
            self.repo.revoke_user_permission(user.id, permission.id)

    def _teacher_view(self, user):
        return {**self.view(user), "can_view_school_summary":
                "statistics.school.read" in self.repo.list_effective_permissions(user.id)}

    def _require_administrator_account_manage(self, actor_id: int) -> None:
        user = self.repo.get_user_by_id_for_update(actor_id)
        if (
            user is None
            or not user.is_active
            or not can_manage_administrator(
                frozenset(self.repo.list_role_codes(actor_id)),
                frozenset(self.repo.list_effective_permissions(actor_id)),
            )
        ):
            raise PermissionDeniedError("需要管理员账号管理能力")

    def _administrator_view(self, user: UserAccount) -> dict:
        return {
            **self.view(user),
            "can_manage_administrators": "administrator_account.manage"
            in self.repo.list_effective_permissions(user.id),
        }

    def list_administrators(
        self, actor: CurrentUser, params: PageParams, query=None, status=None
    ) -> dict:
        self._require_administrator_account_manage(actor.id)
        ids = select(UserRole.user_id).join(Role).where(Role.code == "SUPER_ADMIN")
        stmt = select(UserAccount).where(UserAccount.id.in_(ids))
        if query:
            stmt = stmt.where(
                UserAccount.username.contains(query, autoescape=True)
                | UserAccount.display_name.contains(query, autoescape=True)
            )
        if status:
            stmt = stmt.where(UserAccount.status == status)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        users = self.session.scalars(
            stmt.order_by(UserAccount.id).limit(params.limit).offset(params.offset)
        ).all()
        return {
            "items": [self._administrator_view(u) for u in users],
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    def create_administrator(
        self, actor: CurrentUser, body: AdministratorAccountCreate, request_id
    ) -> dict:
        self.session.rollback()
        lock_admin_registry(self.session)
        self._require_administrator_account_manage(actor.id)
        role = self.repo.get_role_by_code("SUPER_ADMIN")
        if role is None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "请先同步注册表")
        user = UserAccount(
            username=body.username,
            display_name=body.display_name,
            password_hash=hash_password(body.initial_password),
            status="ACTIVE",
            roles=[role],
        )
        self.session.add(user)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(ErrorCode.STATE_CONFLICT, "用户名已存在") from exc
        if body.can_manage_administrators:
            perm = self.repo.get_permission_by_code("administrator_account.manage")
            if perm is None:
                raise ConflictError(ErrorCode.STATE_CONFLICT, "请先同步注册表")
            self.repo.set_user_permission(user.id, perm.id, actor.id)
        self._audit(actor, "account.administrator.create", user, request_id)
        self.session.commit()
        return self._administrator_view(user)

    def update_administrator(
        self, actor: CurrentUser, uid: int, body: AdministratorAccountUpdate, request_id
    ) -> dict:
        self.session.rollback()
        lock_admin_registry(self.session)
        for account_id in sorted({actor.id, uid}):
            self.repo.get_user_by_id_for_update(account_id)
        self._require_administrator_account_manage(actor.id)
        user = self.repo.get_user_by_id_for_update(uid)
        if user is None or "SUPER_ADMIN" not in self.repo.list_role_codes(uid):
            raise NotFoundError("管理员账号不存在")
        self._version(user, body.lock_version)
        before = self._administrator_view(user)
        disabling = body.status is not None and body.status != "ACTIVE"
        if disabling:
            require_another_admin(self.session, uid)
        if before["can_manage_administrators"] and (
            disabling or body.can_manage_administrators is False
        ):
            require_another_administrator_manager(self.session, uid)
        if body.can_manage_administrators is not None:
            perm = self.repo.get_permission_by_code("administrator_account.manage")
            if perm is None:
                raise ConflictError(ErrorCode.STATE_CONFLICT, "请先同步注册表")
            if body.can_manage_administrators:
                self.repo.set_user_permission(uid, perm.id, actor.id)
            else:
                self.repo.revoke_user_permission(uid, perm.id)
        if body.status is not None:
            user.status = body.status
        if body.display_name is not None:
            user.display_name = body.display_name
        user.lock_version += 1
        if disabling or body.can_manage_administrators is False:
            self.repo.revoke_active_sessions(uid, utcnow())
        self._audit(
            actor,
            "account.administrator.update",
            user,
            request_id,
            before=before,
            reason=body.reason,
        )
        self.session.commit()
        return self._administrator_view(user)

    @staticmethod
    def view(user: UserAccount) -> dict:
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "status": user.status,
            "lock_version": user.lock_version,
            "roles": sorted([r.code for r in user.roles]),
        }

    def _manage(self, actor: CurrentUser, target_id: int | None = None) -> UserAccount:
        # 鉴权依赖可能建立旧 RR 快照；写入口从锁定角色行开始独立事务，
        # 等待其他管理员提交后再读取角色，避免最后超管保护依据过期身份。
        self.session.rollback()
        lock_admin_registry(self.session)
        ids = sorted({actor.id, target_id} if target_id is not None else {actor.id})
        locked = {uid: self.repo.get_user_by_id_for_update(uid) for uid in ids}
        active_actor = locked[actor.id]
        if active_actor is None or not active_actor.is_active:
            raise PermissionDeniedError("操作者账号已停用")
        self.identity._require_actor_permission(actor.id, PermissionCode.ACCOUNT_MANAGE.value)
        if RoleCode.SUPER_ADMIN.value not in self.repo.list_role_codes(actor.id):
            raise PermissionDeniedError()
        target = locked[target_id if target_id is not None else actor.id]
        if target is None:
            raise NotFoundError("教师账号不存在")
        if target_id is not None:
            target_roles = self.repo.list_role_codes(target_id)
            if "TEACHER_ADMIN" not in target_roles or "SUPER_ADMIN" in target_roles:
                raise NotFoundError("教师账号不存在")
        return target

    def _audit(
        self,
        actor: CurrentUser,
        action: str,
        user: UserAccount,
        request_id: str | None,
        *,
        before: dict | None = None,
        reason: str | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                actor_user_id=actor.id,
                action=action,
                resource_type="user_account",
                resource_id=str(user.id),
                before_json=before,
                after_json=self._teacher_view(user)
                if action.startswith("account.teacher.") else self.view(user),
                reason=reason,
                request_id=request_id,
            )
        )

    def list_accounts(
        self, actor: CurrentUser, params: PageParams, query: str | None, status: str | None
    ) -> dict:
        roles = set(self.repo.list_role_codes(actor.id))
        if RoleCode.SUPER_ADMIN.value not in roles and RoleCode.TEACHER_ADMIN.value not in roles:
            self.identity._require_actor_permission(actor.id, PermissionCode.ACCOUNT_READ.value)
        teacher = (
            select(UserRole.user_id)
            .join(Role)
            .where(
                Role.code.in_(
                    [
                        RoleCode.TEACHER_ADMIN.value,
                        RoleCode.SUPER_ADMIN.value,
                        RoleCode.STUDENT_AFFAIRS_MANAGER.value,
                    ]
                )
            )
        )
        stmt = select(UserAccount).where(UserAccount.id.in_(teacher))
        from app.modules.identity.account_visibility import management_users
        visible = management_users(self.session, actor.id,
            "role.assign" if RoleCode.TEACHER_ADMIN.value in roles and RoleCode.SUPER_ADMIN.value not in roles else "account.read")
        stmt = stmt.where(UserAccount.id.in_(visible.with_only_columns(UserAccount.id)))
        if query:
            stmt = stmt.where(
                UserAccount.username.contains(query, autoescape=True)
                | UserAccount.display_name.contains(query, autoescape=True)
            )
        if status:
            stmt = stmt.where(UserAccount.status == status)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(self.session.execute(
            stmt.order_by(UserAccount.id).limit(params.limit).offset(params.offset)
        ).scalars())
        granted = set(self.session.scalars(select(UserPermission.user_id).join(
            Permission, Permission.id == UserPermission.permission_id).where(
            UserPermission.user_id.in_([r.id for r in rows]),
            Permission.code == "statistics.school.read")))
        return {
            "items": [{**self.view(r), "can_view_school_summary": r.id in granted
                       or any(role.code == "SUPER_ADMIN" for role in r.roles)}
                      for r in rows],
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    @atomic_write
    def create(
        self, actor: CurrentUser, body: TeacherAccountCreate, request_id: str | None
    ) -> dict:
        self._manage(actor)
        from app.modules.academic.enrollment_models import TeacherCollegeBinding
        from app.modules.organization.models import College

        college = self.session.get(College, body.college_id)
        if college is None or college.status != "ACTIVE":
            raise NotFoundError("教师必须选择有效学院")
        role = self.repo.get_role_by_code(RoleCode.TEACHER_ADMIN.value)
        if role is None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "请先同步权限注册表")
        user = UserAccount(
            username=body.username,
            display_name=body.display_name,
            password_hash=hash_password(body.initial_password),
            status=UserStatus.ACTIVE.value,
            roles=[role],
        )
        self.session.add(user)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(ErrorCode.STATE_CONFLICT, "用户名已存在") from exc
        self.session.add(TeacherCollegeBinding(user_id=user.id, college_id=college.id))
        college.authorization_revision += 1
        if body.can_view_school_summary:
            self._school_summary_permission(actor, user, True)
        self._audit(actor, "account.teacher.create", user, request_id)
        self.session.commit()
        return self._teacher_view(user)

    @staticmethod
    def _version(user: UserAccount, version: int) -> None:
        if user.lock_version != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "账号已变化，请刷新后重试")

    @atomic_write
    def update(
        self, actor: CurrentUser, uid: int, body: TeacherAccountUpdate, request_id: str | None
    ) -> dict:
        user = self._manage(actor, uid)
        self._version(user, body.lock_version)
        before = self.view(user)
        before["can_view_school_summary"] = self._teacher_view(user)["can_view_school_summary"]
        if body.can_view_school_summary is not None:
            self._school_summary_permission(actor, user, body.can_view_school_summary)
            if not body.can_view_school_summary:
                self.repo.revoke_active_sessions(uid, utcnow())
        if body.status is not None and body.status != UserStatus.ACTIVE.value:
            if RoleCode.SUPER_ADMIN.value in self.repo.list_role_codes(uid):
                require_another_admin(self.session, uid)
            self.repo.revoke_active_sessions(uid, utcnow())
        if body.status is not None:
            user.status = body.status
        if body.display_name is not None:
            user.display_name = body.display_name
        user.lock_version += 1
        self._audit(
            actor, "account.teacher.update", user, request_id, before=before, reason=body.reason
        )
        self.session.commit()
        return self._teacher_view(user)

    def reset_password(
        self, actor: CurrentUser, uid: int, body: PasswordReset, request_id: str | None
    ) -> None:
        self.session.rollback()
        lock_admin_registry(self.session)
        ids = sorted({actor.id, uid})
        locked = {user_id: self.repo.get_user_by_id_for_update(user_id) for user_id in ids}
        active_actor = locked[actor.id]
        if active_actor is None or not active_actor.is_active:
            raise PermissionDeniedError("操作者账号已停用")

        target = locked[uid]
        if target is None:
            raise NotFoundError("目标账号不存在")

        target_roles = set(self.repo.list_role_codes(uid))

        if RoleCode.SUPER_ADMIN.value in target_roles:
            self._require_administrator_account_manage(actor.id)
        elif RoleCode.TEACHER_ADMIN.value in target_roles:
            self.identity._require_actor_permission(actor.id, PermissionCode.ACCOUNT_MANAGE.value)
            if not actor.has_role(RoleCode.SUPER_ADMIN.value):
                raise PermissionDeniedError("仅超级管理员可重置教工密码")
        elif RoleCode.STUDENT_AFFAIRS_MANAGER.value in target_roles:
            from app.modules.identity.role_scope import require_student_scope
            if target.student_id is None:
                raise ConflictError(message="负责人缺少有效学生绑定")
            require_student_scope(self.session, actor.id, "role.assign", target.student_id)
            can_manage = (
                actor.has_role(RoleCode.SUPER_ADMIN.value)
                or actor.has_role(RoleCode.TEACHER_ADMIN.value)
                or actor.has_permission(PermissionCode.ROLE_ASSIGN.value)
                or actor.has_permission(PermissionCode.ACCOUNT_MANAGE.value)
            )
            if not can_manage:
                raise PermissionDeniedError("无权为学生负责人设置密码")
            if not target.username and target.student_id:
                student = self.session.get(Student, target.student_id)
                if student:
                    target.username = student.student_no
        else:
            raise NotFoundError("该账号不支持密码重置")

        self._version(target, body.lock_version)
        target.password_hash = hash_password(body.new_password)
        target.failed_login_count = 0
        target.locked_until = None
        target.lock_version += 1
        self.repo.revoke_active_sessions(uid, utcnow())
        self._audit(actor, "account.password.reset", target, request_id, reason=body.reason)
        self.session.commit()

    def change_password(
        self, actor: CurrentUser, body: PasswordChange, request_id: str | None
    ) -> None:
        user = self.repo.get_user_by_id_for_update(actor.id)
        if (
            user is None
            or not user.is_active
            or not user.password_hash
            or not body.current_password
            or not verify_password(body.current_password, user.password_hash)
        ):
            raise PermissionDeniedError("当前口令不正确或账号未启用密码登录")
        user.password_hash = hash_password(body.new_password)
        user.lock_version += 1
        self.repo.revoke_active_sessions(user.id, utcnow())
        self._audit(actor, "account.password.change", user, request_id)
        self.session.commit()
