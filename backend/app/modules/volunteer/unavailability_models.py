"""A group approves the request; its busy interval applies to every group."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class VolunteerUnavailability(TimestampMixin, Base):
    __tablename__ = "volunteer_unavailability"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_volunteer_unavailability_times"),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELED')",
            name="ck_volunteer_unavailability_status",
        ),
        Index(
            "ix_volunteer_unavailability_student_status_start", "student_id", "status", "starts_at"
        ),
        Index("ix_volunteer_unavailability_group_semester", "group_id", "semester_id"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(ForeignKey("volunteer_group.id", ondelete="RESTRICT"))
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    starts_at: Mapped[datetime] = mapped_column(DATETIME_3)
    ends_at: Mapped[datetime] = mapped_column(DATETIME_3)
    reason: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    requested_by: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    decision_note: Mapped[str] = mapped_column(String(512), default="")
