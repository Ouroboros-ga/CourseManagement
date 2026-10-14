"""组与不可变配置版本；显式范围引用阻止删掉已使用类型。"""

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, Base, PkBigInt, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class VolunteerGroup(TimestampMixin, Base):
    __tablename__ = "volunteer_group"
    __table_args__ = (
        UniqueConstraint("college_id", "id", name="uq_volunteer_group_college_id"),
        UniqueConstraint("college_id", "normalized_name", name="uq_volunteer_group_name"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE')", name="volunteer_group_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin").with_variant(String(128), "sqlite")
    )
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    starts_on: Mapped[date | None] = mapped_column(DATE_COL)
    ends_on: Mapped[date | None] = mapped_column(DATE_COL)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    config_version: Mapped[int] = mapped_column(Integer, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class GroupConfigVersion(TimestampMixin, Base):
    __tablename__ = "group_config_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["college_id", "group_id"],
            ["volunteer_group.college_id", "volunteer_group.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("group_id", "version", name="uq_group_config_version"),
        UniqueConstraint("college_id", "id", name="uq_group_config_college_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(PkBigInt)
    version: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[dict] = mapped_column(JSON)
    published_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))


class GroupScopeType(Base):
    __tablename__ = "group_scope_type"
    __table_args__ = (
        ForeignKeyConstraint(
            ["college_id", "config_id"],
            ["group_config_version.college_id", "group_config_version.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["college_id", "course_type_id"],
            ["course_type.college_id", "course_type.id"],
            ondelete="RESTRICT",
        ),
        MYSQL_TABLE_ARGS,
    )

    config_id: Mapped[int] = mapped_column(PkBigInt, primary_key=True)
    course_type_id: Mapped[int] = mapped_column(PkBigInt, primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    is_inspection_scope: Mapped[bool] = mapped_column(Boolean, default=True)
