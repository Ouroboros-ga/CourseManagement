"""稳定学院归属与带日期的学籍事实。旧 current 字段只作为兼容投影。"""

from datetime import date
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS
from app.modules.organization.models import College as College


class TeacherCollegeBinding(TimestampMixin, Base):
    __tablename__ = "teacher_college_binding"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), primary_key=True
    )
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class StudentManagerAppointment(TimestampMixin, Base):
    __tablename__ = "student_manager_appointment"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_manager_appointment_range",
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), index=True
    )
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date | None] = mapped_column(DATE_COL)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON)


class StudentEnrollment(TimestampMixin, Base):
    """半开区间 [effective_from,effective_to)，快照不随班级改名漂移。

    迁移只确认当前归属，historical_confirmed=False 的基线不能作为过往学籍证据。
    superseded 只用于保留被日期核实取代的迁移基线，不删除源事实。
    """

    __tablename__ = "student_enrollment"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="ck_enrollment_range"
        ),
        UniqueConstraint("student_id", "revision", name="uq_enrollment_student_revision"),
        CheckConstraint(
            "status IN ('ENROLLED','SUSPENDED','GRADUATED','WITHDRAWN')",
            name="ck_enrollment_status",
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), index=True
    )
    administrative_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("administrative_class.id", ondelete="RESTRICT")
    )
    college_id: Mapped[int | None] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date | None] = mapped_column(DATE_COL)
    status: Mapped[str] = mapped_column(String(16), default="ENROLLED")
    revision: Mapped[int] = mapped_column(Integer)
    historical_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class EnrollmentChange(TimestampMixin, Base):
    """变更与交接清单；撤销仅允许尚未生效的计划，已生效事实以新更正留痕。"""

    __tablename__ = "enrollment_change"
    __table_args__ = (
        UniqueConstraint("student_id", "idempotency_key", name="uq_enrollment_change_key"),
        CheckConstraint(
            "kind IN ('TRANSFER','RETURN','SUSPEND','GRADUATE','WITHDRAW')",
            name="ck_enrollment_change_kind",
        ),
        CheckConstraint(
            "state IN ('SCHEDULED','APPLIED','CANCELED')", name="ck_enrollment_change_state"
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), index=True
    )
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[date] = mapped_column(DATE_COL, index=True)
    source_enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("student_enrollment.id", ondelete="RESTRICT")
    )
    target_enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("student_enrollment.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(512))
    impact: Mapped[dict[str, Any]] = mapped_column(JSON)


class TeachingClassAudience(Base):
    """明确整班课程来源；不能从选修课学生并集猜出公共课程。"""

    __tablename__ = "teaching_class_audience"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT"), primary_key=True
    )
    administrative_class_id: Mapped[int] = mapped_column(
        ForeignKey("administrative_class.id", ondelete="RESTRICT"), primary_key=True
    )


class CourseParticipation(TimestampMixin, Base):
    __tablename__ = "course_participation"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="ck_participation_range"
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    teaching_class_id: Mapped[int] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), index=True
    )
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date | None] = mapped_column(DATE_COL)
    source: Mapped[str] = mapped_column(String(32), default="EXPLICIT")


class StudentDataPlan(TimestampMixin, Base):
    __tablename__ = "student_data_plan"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    id: Mapped[int] = pk_column()
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PREVIEW")
    lock_version: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[date] = mapped_column(DATE_COL)
