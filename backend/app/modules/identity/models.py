"""身份与基础数据模块 ORM 模型（技术方案 9.1）。

采用 SQLAlchemy 2.x DeclarativeBase + Mapped + mapped_column 风格。
枚举以字符串值存储并加必要 CHECK 约束，不映射成 MySQL 原生 ENUM。
表映射只定义结构，业务归属判断在各模块 permissions/service。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import (
    DATETIME_3,
    Base,
    CreateTimeMixin,
    TimestampMixin,
    pk_column,
)
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class UserStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BANNED = "BANNED"


class ClientType(enum.StrEnum):
    WEB = "WEB"
    WECHAT = "WECHAT"


class BindingTokenStatus(enum.StrEnum):
    UNUSED = "UNUSED"
    USED = "USED"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------------------- #
# 账号与身份
# --------------------------------------------------------------------------- #
class UserAccount(TimestampMixin, Base):
    """系统账号。username 与 student_id 均为唯一可空（MySQL 允许多个 NULL）。"""

    __tablename__ = "user_account"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), unique=True
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UserStatus.ACTIVE.value, server_default=text("'ACTIVE'")
    )
    failed_login_count: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME_3)
    # 乐观锁版本：角色/个人权限变更用条件更新检测并发冲突（技术方案 5、9.1）。
    lock_version: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), nullable=False
    )

    roles: Mapped[list[Role]] = relationship(
        secondary="user_role", back_populates="users", lazy="selectin"
    )

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE.value


class WechatIdentity(CreateTimeMixin, Base):
    """微信身份。未来多小程序时身份唯一键为 appid + openid。"""

    __tablename__ = "wechat_identity"
    __table_args__ = (
        UniqueConstraint("appid", "openid", name="uq_wechat_identity_appid_openid"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    appid: Mapped[str] = mapped_column(String(64), nullable=False)
    openid: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )


# --------------------------------------------------------------------------- #
# 会话（必需表）
# --------------------------------------------------------------------------- #
class AuthSession(CreateTimeMixin, Base):
    """登录会话。保存刷新凭证摘要与刷新族，支持轮换与重放检测。

    访问令牌含会话引用；接口既校验签名也校验此表有效性（不能仅因 JWT 有效就接受）。
    """

    __tablename__ = "auth_session"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_type: Mapped[str] = mapped_column(String(16), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    refresh_family_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    last_used_at: Mapped[datetime | None] = mapped_column(DATETIME_3)

    @property
    def is_valid(self) -> bool:
        from app.core.database import utcnow

        return self.revoked_at is None and self.expires_at > utcnow()


# --------------------------------------------------------------------------- #
# 绑定码
# --------------------------------------------------------------------------- #
class IdentityBindingToken(CreateTimeMixin, Base):
    """一次性学生绑定码。仅保存不可逆摘要；有效期 + 使用/失败次数限制。"""

    __tablename__ = "identity_binding_token"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UNUSED','USED','EXPIRED')", name="ck_status_enum"
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BindingTokenStatus.UNUSED.value,
        server_default=text("'UNUSED'"),
    )
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    failed_attempts: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), nullable=False
    )


# --------------------------------------------------------------------------- #
# 角色与权限
# --------------------------------------------------------------------------- #
class Role(TimestampMixin, Base):
    __tablename__ = "role"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    users: Mapped[list[UserAccount]] = relationship(
        secondary="user_role", back_populates="roles", lazy="selectin"
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permission", back_populates="roles", lazy="selectin"
    )


class Permission(TimestampMixin, Base):
    __tablename__ = "permission"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary="role_permission", back_populates="permissions", lazy="selectin"
    )


class UserRole(Base):
    """用户—角色关联，联合主键。"""

    __tablename__ = "user_role"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )


class RolePermission(Base):
    """角色—权限关联，联合主键。"""

    __tablename__ = "role_permission"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permission.id", ondelete="CASCADE"), primary_key=True
    )


class UserPermission(CreateTimeMixin, Base):
    """逐人可选权限授权。存在有效记录即开启，删除即关闭（技术方案 6.3）。"""

    __tablename__ = "user_permission"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", name="uq_user_permission_user_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permission.id", ondelete="CASCADE"), nullable=False
    )
    granted_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
