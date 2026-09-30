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
from app.modules.audit.models import AuditLog
from app.modules.identity.account_schemas import (
    PasswordChange,
    PasswordReset,
    TeacherAccountCreate,
    TeacherAccountUpdate,
)
from app.modules.identity.models import Role, UserAccount, UserRole, UserStatus
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser, IdentityService


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


class AccountService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = IdentityRepository(session)
        self.identity = IdentityService(session)

    @staticmethod
    def view(user: UserAccount) -> dict:
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "status": user.status,
            "lock_version": user.lock_version,
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
        if target_id is not None and RoleCode.TEACHER_ADMIN.value not in (
            self.repo.list_role_codes(target_id)
        ):
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
                after_json=self.view(user),
                reason=reason,
                request_id=request_id,
            )
        )

    def list_accounts(
        self, actor: CurrentUser, params: PageParams, query: str | None, status: str | None
    ) -> dict:
        self.identity._require_actor_permission(actor.id, PermissionCode.ACCOUNT_READ.value)
        teacher = (
            select(UserRole.user_id).join(Role).where(Role.code == RoleCode.TEACHER_ADMIN.value)
        )
        stmt = select(UserAccount).where(UserAccount.id.in_(teacher))
        if query:
            stmt = stmt.where(
                UserAccount.username.contains(query, autoescape=True)
                | UserAccount.display_name.contains(query, autoescape=True)
            )
        if status:
            stmt = stmt.where(UserAccount.status == status)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = self.session.execute(
            stmt.order_by(UserAccount.id).limit(params.limit).offset(params.offset)
        ).scalars()
        return {
            "items": [self.view(r) for r in rows],
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
        }

    def create(
        self, actor: CurrentUser, body: TeacherAccountCreate, request_id: str | None
    ) -> dict:
        self._manage(actor)
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
        self._audit(actor, "account.teacher.create", user, request_id)
        self.session.commit()
        return self.view(user)

    @staticmethod
    def _version(user: UserAccount, version: int) -> None:
        if user.lock_version != version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "账号已变化，请刷新后重试")

    def update(
        self, actor: CurrentUser, uid: int, body: TeacherAccountUpdate, request_id: str | None
    ) -> dict:
        user = self._manage(actor, uid)
        self._version(user, body.lock_version)
        before = self.view(user)
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
        return self.view(user)

    def reset_password(
        self, actor: CurrentUser, uid: int, body: PasswordReset, request_id: str | None
    ) -> None:
        user = self._manage(actor, uid)
        self._version(user, body.lock_version)
        user.password_hash = hash_password(body.new_password)
        user.failed_login_count = 0
        user.locked_until = None
        user.lock_version += 1
        self.repo.revoke_active_sessions(uid, utcnow())
        self._audit(actor, "account.password.reset", user, request_id, reason=body.reason)
        self.session.commit()

    def change_password(
        self, actor: CurrentUser, body: PasswordChange, request_id: str | None
    ) -> None:
        user = self.repo.get_user_by_id_for_update(actor.id)
        if (
            user is None
            or not user.is_active
            or not user.password_hash
            or not verify_password(body.current_password, user.password_hash)
        ):
            raise PermissionDeniedError("当前口令不正确或账号未启用密码登录")
        user.password_hash = hash_password(body.new_password)
        user.lock_version += 1
        self.repo.revoke_active_sessions(user.id, utcnow())
        self._audit(actor, "account.password.change", user, request_id)
        self.session.commit()
