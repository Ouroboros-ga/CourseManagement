"""身份模块仓储层：仅执行查询，复用 Service 传入的 Session，不自行 commit。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identity.models import (
    AuthSession,
    IdentityBindingToken,
    Permission,
    Role,
    RolePermission,
    Student,
    UserAccount,
    UserPermission,
    UserRole,
    WechatIdentity,
)
from app.modules.identity.policy import OPTIONAL_PERMISSION_CODES


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---- 账号 ----
    def get_user_by_id(self, user_id: int) -> UserAccount | None:
        return self._session.get(UserAccount, user_id)

    def get_user_by_id_for_update(self, user_id: int) -> UserAccount | None:
        """SELECT ... FOR UPDATE 锁定账号行，并强制回填最新列值。

        变更服务在同一事务内锁定操作者与目标账号，靠 with_for_update 串行化并发写；
        populate_existing 确保读到其它已提交事务刷新过的 lock_version（否则命中会话缓存）。
        """
        stmt = (
            select(UserAccount)
            .where(UserAccount.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_user_by_username(self, username: str) -> UserAccount | None:
        stmt = select(UserAccount).where(UserAccount.username == username)
        return self._session.execute(stmt).scalar_one_or_none()

    # ---- 角色与权限 ----
    def list_role_codes(self, user_id: int) -> list[str]:
        rows = self._session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        ).all()
        return sorted(row[0] for row in rows)

    def list_effective_permissions(self, user_id: int) -> list[str]:
        """角色权限 ∪ 逐人可选权限（技术方案 6.3）。

        个人授权分支仅认三项可配置权限（OPTIONAL_PERMISSION_CODES）：
        有效个人权限只来自负责人身份 + 三项许可清单（P1 第 6 步）；
        负责人角色被撤销时其个人授权已在变更服务中清除，重新授角色不自动恢复。
        """
        role_perms = self._session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        ).all()
        user_perms = self._session.execute(
            select(Permission.code)
            .join(UserPermission, UserPermission.permission_id == Permission.id)
            .where(
                UserPermission.user_id == user_id,
                Permission.code.in_(OPTIONAL_PERMISSION_CODES),
            )
        ).all()
        codes = {row[0] for row in role_perms} | {row[0] for row in user_perms}
        return sorted(codes)

    def get_permission_by_code(self, code: str) -> Permission | None:
        stmt = select(Permission).where(Permission.code == code)
        return self._session.execute(stmt).scalar_one_or_none()

    def has_permission_code(self, code: str) -> bool:
        return self.get_permission_by_code(code) is not None

    def get_role_by_code(self, code: str) -> Role | None:
        return self._session.execute(
            select(Role).where(Role.code == code)
        ).scalar_one_or_none()

    def get_or_create_role(self, code: str, name: str) -> Role:
        role = self._session.execute(
            select(Role).where(Role.code == code)
        ).scalar_one_or_none()
        if role is None:
            role = Role(code=code, name=name)
            self._session.add(role)
            self._session.flush()
        return role

    def get_or_create_permission(self, code: str, name: str) -> Permission:
        perm = self._session.execute(
            select(Permission).where(Permission.code == code)
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, name=name)
            self._session.add(perm)
            self._session.flush()
        return perm

    def grant_role(self, user_id: int, role_id: int) -> None:
        from app.modules.identity.models import UserRole

        exists = self._session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id
            )
        ).scalar_one_or_none()
        if exists is None:
            self._session.add(UserRole(user_id=user_id, role_id=role_id))
            self._session.flush()

    def revoke_role(self, user_id: int, role_id: int) -> None:
        exists = self._session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id
            )
        ).scalar_one_or_none()
        if exists is not None:
            self._session.delete(exists)
            self._session.flush()

    def set_user_permission(self, user_id: int, permission_id: int, granted_by: int) -> None:
        exists = self._session.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.permission_id == permission_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            self._session.add(
                UserPermission(
                    user_id=user_id, permission_id=permission_id, granted_by=granted_by
                )
            )
            self._session.flush()

    def revoke_user_permission(self, user_id: int, permission_id: int) -> None:
        row = self._session.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.permission_id == permission_id,
            )
        ).scalar_one_or_none()
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    # ---- 授权管理支撑（受限目标选择器 + 同事务变更服务）----
    def list_all_users(self) -> list[UserAccount]:
        """角色分配目标选择器：返回全部账号（按 ID 稳定排序）。"""
        stmt = select(UserAccount).order_by(UserAccount.id)
        return list(self._session.execute(stmt).scalars().all())

    def list_users_with_role(self, role_code: str) -> list[UserAccount]:
        """可选权限目标选择器：仅返回持有指定角色（负责人）的账号。"""
        stmt = (
            select(UserAccount)
            .join(UserRole, UserRole.user_id == UserAccount.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == role_code)
            .order_by(UserAccount.id)
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_optional_grant_codes(self, user_id: int) -> list[str]:
        """当前逐人开启的可选权限 code（限定在三项许可清单内）。"""
        rows = self._session.execute(
            select(Permission.code)
            .join(UserPermission, UserPermission.permission_id == Permission.id)
            .where(
                UserPermission.user_id == user_id,
                Permission.code.in_(OPTIONAL_PERMISSION_CODES),
            )
        ).all()
        return sorted(row[0] for row in rows)

    def clear_optional_grants(self, user_id: int) -> int:
        """删除该用户的全部可选授权（撤销负责人角色时同事务清理）。返回删除条数。"""
        rows = self._session.execute(
            select(UserPermission)
            .join(Permission, Permission.id == UserPermission.permission_id)
            .where(
                UserPermission.user_id == user_id,
                Permission.code.in_(OPTIONAL_PERMISSION_CODES),
            )
        ).scalars().all()
        for row in rows:
            self._session.delete(row)
        self._session.flush()
        return len(rows)

    # ---- 会话 ----
    def get_session_by_id(self, session_id: int) -> AuthSession | None:
        return self._session.get(AuthSession, session_id)

    def get_session_by_refresh_hash(self, refresh_hash: str) -> AuthSession | None:
        stmt = select(AuthSession).where(AuthSession.refresh_token_hash == refresh_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def sessions_in_family(self, family_id: str) -> list[AuthSession]:
        stmt = select(AuthSession).where(AuthSession.refresh_family_id == family_id)
        return list(self._session.execute(stmt).scalars().all())

    def revoke_active_sessions(self, user_id: int, now) -> int:
        """撤销某用户当前全部有效会话（换绑/停用后即时踢出）。返回撤销条数。

        仅置 revoked_at，不 commit——由调用方在同一事务内与业务写入一起提交。
        """
        rows = self._session.execute(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
        ).scalars().all()
        count = 0
        for s in rows:
            s.revoked_at = now
            count += 1
        self._session.flush()
        return count

    # ---- 学生与绑定码 ----
    def get_student_by_no(self, student_no: str) -> Student | None:
        stmt = select(Student).where(Student.student_no == student_no)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_student_by_id(self, student_id: int) -> Student | None:
        return self._session.get(Student, student_id)

    def get_binding_token_by_hash(self, token_hash: str) -> IdentityBindingToken | None:
        stmt = select(IdentityBindingToken).where(
            IdentityBindingToken.token_hash == token_hash
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_binding_token_by_hash_for_update(
        self, token_hash: str
    ) -> IdentityBindingToken | None:
        """SELECT ... FOR UPDATE 锁定绑定码行，串行化对同一码的并发核销。

        populate_existing 确保持锁后读到其它已提交事务对 status/used_at 的最新写入
        （InnoDB 加锁读在持锁时放弃旧快照读最新已提交版本），从而保证一次性核销不变量。
        """
        stmt = (
            select(IdentityBindingToken)
            .where(IdentityBindingToken.token_hash == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_binding_token_by_id(self, token_id: int) -> IdentityBindingToken | None:
        return self._session.get(IdentityBindingToken, token_id)

    def create_binding_token(
        self, student_id: int, token_hash: str, expires_at
    ) -> IdentityBindingToken:
        from app.modules.identity.models import BindingTokenStatus

        token = IdentityBindingToken(
            student_id=student_id,
            token_hash=token_hash,
            status=BindingTokenStatus.UNUSED.value,
            expires_at=expires_at,
        )
        self._session.add(token)
        self._session.flush()
        return token

    # ---- 微信身份（P2）----
    def get_user_by_wechat(self, appid: str, openid: str) -> UserAccount | None:
        """按 appid + openid 唯一定位已绑定的账号；无则 None（首次登录需建号）。"""
        stmt = (
            select(UserAccount)
            .join(WechatIdentity, WechatIdentity.user_id == UserAccount.id)
            .where(WechatIdentity.appid == appid, WechatIdentity.openid == openid)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def add_wechat_identity(self, user_id: int, appid: str, openid: str) -> WechatIdentity:
        wi = WechatIdentity(user_id=user_id, appid=appid, openid=openid)
        self._session.add(wi)
        self._session.flush()
        return wi

    def add(self, obj: object) -> None:
        self._session.add(obj)
