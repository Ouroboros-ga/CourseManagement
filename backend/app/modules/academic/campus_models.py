"""院级可维护课程类型；与旧 InspectionType 兼容枚举无隐式映射。"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class CourseType(TimestampMixin, Base):
    __tablename__ = "course_type"
    __table_args__ = (
        UniqueConstraint("college_id", "id", name="uq_course_type_college_id"),
        UniqueConstraint("college_id", "code", name="uq_course_type_college_code"),
        UniqueConstraint("college_id", "builtin_key", name="uq_course_type_builtin"),
        UniqueConstraint("college_id", "normalized_name", name="uq_course_type_college_name"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="course_type_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(32))
    builtin_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(
        String(128, collation="utf8mb4_bin").with_variant(String(128), "sqlite")
    )
    description: Mapped[str] = mapped_column(String(512), default="")
    display_color: Mapped[str] = mapped_column(String(7), default="#409EFF")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
