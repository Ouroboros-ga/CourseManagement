from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AutoChangePolicy(TimestampMixin, Base):
    __tablename__ = "auto_change_policy"
    __table_args__ = (
        UniqueConstraint("college_id", "group_id", "semester_id", name="uq_auto_change_scope"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(ForeignKey("volunteer_group.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    authorizer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_cutoff_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    enabled_at: Mapped[datetime | None] = mapped_column(DATETIME_3)


class AutoChangeExecution(TimestampMixin, Base):
    """One policy-bound attempt per volunteer request; the receipt is a domain fact."""

    __tablename__ = "auto_change_execution"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    id: Mapped[int] = pk_column()
    environment: Mapped[str | None] = mapped_column(String(32))
    policy_id: Mapped[int] = mapped_column(ForeignKey("auto_change_policy.id", ondelete="RESTRICT"))
    request_id: Mapped[int] = mapped_column(
        ForeignKey("assignment_change_request.id", ondelete="RESTRICT"), unique=True
    )
    authorizer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED", index=True)
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("assignment_confirmation_plan.id", ondelete="RESTRICT")
    )
    plan_revision: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
