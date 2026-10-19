"""教职工档案与资源关系；显示姓名及管理员角色均不产生任职授权。

有效期为半开区间 [effective_from, effective_to)。重叠和交接由后续关系
写服务锁定稳定父行后检查；数据库 CHECK 不能替代跨行并发控制。
"""

from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class FacultyStaff(TimestampMixin, Base):
    __tablename__ = "faculty_staff"
    __table_args__ = (
        UniqueConstraint("school_id", "staff_no", name="uq_staff_school_number"),
        UniqueConstraint(
            "school_id", "temporary_staff_no", name="uq_staff_school_temporary_number"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="staff_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"))
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    staff_no: Mapped[str] = mapped_column(String(64))
    # 补充真实工号时保留原临时工号，只用于微信绑定；不改变档案或账号主键。
    temporary_staff_no: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="ACTIVE", server_default=text("'ACTIVE'")
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))


class TeachingStaffAssignment(TimestampMixin, Base):
    __tablename__ = "teaching_staff_assignment"
    __table_args__ = (
        CheckConstraint(
            "(anchor_type = 'LOCAL' AND teaching_class_id IS NOT NULL "
            "AND academic_offering_id IS NULL) OR "
            "(anchor_type = 'SHARED' AND teaching_class_id IS NULL "
            "AND academic_offering_id IS NOT NULL)",
            name="teaching_staff_anchor",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="teaching_staff_dates"
        ),
        Index(
            "ix_teaching_staff_current", "staff_id", "semester_id", "effective_from", "effective_to"
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    staff_id: Mapped[int] = mapped_column(ForeignKey("faculty_staff.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    anchor_type: Mapped[str] = mapped_column(String(16))
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT"), index=True
    )
    academic_offering_id: Mapped[str | None] = mapped_column(
        ForeignKey("academic_offering.id", ondelete="RESTRICT"), index=True
    )
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date | None] = mapped_column(DATE_COL)
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))


class ClassStaffResponsibility(TimestampMixin, Base):
    __tablename__ = "class_staff_responsibility"
    __table_args__ = (
        CheckConstraint("duty IN ('HEAD_TEACHER','COUNSELOR')", name="staff_duty"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="class_staff_dates"
        ),
        Index("ix_class_staff_current", "staff_id", "effective_from", "effective_to"),
        Index("ix_class_staff_handover", "administrative_class_id", "duty", "effective_from"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    staff_id: Mapped[int] = mapped_column(ForeignKey("faculty_staff.id", ondelete="RESTRICT"))
    administrative_class_id: Mapped[int] = mapped_column(
        ForeignKey("administrative_class.id", ondelete="RESTRICT")
    )
    duty: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date | None] = mapped_column(DATE_COL)
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
