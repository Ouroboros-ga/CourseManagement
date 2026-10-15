"""School period templates: every revision is immutable, adoption is a copy."""

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class SchoolTimeTemplate(TimestampMixin, Base):
    __tablename__ = "school_time_template"
    __table_args__ = (
        UniqueConstraint("school_id", "normalized_name", name="uq_school_time_template_name"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_school_time_template_status"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin").with_variant(String(128), "sqlite")
    )
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    latest_version: Mapped[int] = mapped_column(Integer, default=1)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class SchoolTimeTemplateVersion(TimestampMixin, Base):
    __tablename__ = "school_time_template_version"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_school_time_template_version"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    template_id: Mapped[int] = mapped_column(
        ForeignKey("school_time_template.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    periods: Mapped[list[dict]] = mapped_column(JSON)
    published_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
