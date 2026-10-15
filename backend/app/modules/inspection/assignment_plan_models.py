from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin
from app.core.db import MYSQL_TABLE_ARGS


class AssignmentConfirmationPlan(TimestampMixin, Base):
    __tablename__ = "assignment_confirmation_plan"
    __table_args__ = (
        CheckConstraint("status IN ('READY','COMMITTED')", name="ck_assignment_plan_status"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(ForeignKey("volunteer_group.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="READY")
    revision: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
