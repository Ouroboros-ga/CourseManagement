"""稳定学院实体与院级完整授权；不使用 NULL 表示全校范围。"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class School(TimestampMixin, Base):
    __tablename__ = "school"
    __table_args__ = (
        UniqueConstraint("singleton_key", name="uq_school_singleton_key"),
        CheckConstraint("singleton_key = 1", name="school_singleton"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True)
    singleton_key: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(128))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class College(TimestampMixin, Base):
    __tablename__ = "college"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_college_school_code"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="college_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    authorization_revision: Mapped[int] = mapped_column(Integer, default=1)
    configuration_revision: Mapped[int] = mapped_column(Integer, default=1)


class ScopedGrant(TimestampMixin, Base):
    """学院动作授权，可附指定资源上限；旧空范围明确表示院级授权。"""

    __tablename__ = "scoped_grant"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED')", name="scoped_grant_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"),
        index=True,
    )
    actions: Mapped[list[str]] = mapped_column(JSON)
    resource_scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    expires_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    granted_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
