from datetime import date

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class GroupRange(TimestampMixin):
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("volunteer_group.id", ondelete="RESTRICT"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), index=True
    )
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), index=True
    )
    effective_from: Mapped[date] = mapped_column(DATE_COL)
    effective_to: Mapped[date] = mapped_column(DATE_COL)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class VolunteerGroupMember(GroupRange, Base):
    __tablename__ = "volunteer_group_member"
    __table_args__ = (
        CheckConstraint("effective_to > effective_from", name="ck_group_member_dates"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_group_member_status"),
        UniqueConstraint(
            "group_id", "student_id", "semester_id", "effective_from", name="uq_group_member_start"
        ),
        MYSQL_TABLE_ARGS,
    )


class VolunteerGroupSupport(GroupRange, Base):
    __tablename__ = "volunteer_group_support"
    __table_args__ = (
        CheckConstraint("effective_to > effective_from", name="ck_group_support_dates"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_group_support_status"),
        MYSQL_TABLE_ARGS,
    )
    authorized_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    # A later group publication cannot enlarge this super-admin authorization.
    scope_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
