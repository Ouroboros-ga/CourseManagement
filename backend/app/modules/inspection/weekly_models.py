"""Weekly policy and per-target-week receipts; no additional generic queue table."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATE_COL, DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class WeeklyInspectionPlan(TimestampMixin, Base):
    __tablename__ = "weekly_inspection_plan"
    __table_args__ = (
        UniqueConstraint(
            "environment", "college_id", "group_id", "semester_id", name="uq_weekly_plan_scope"
        ),
        Index("ix_weekly_plan_due", "environment", "enabled", "id"),
        CheckConstraint("version >= 1", name="version"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    environment: Mapped[str] = mapped_column(String(32))
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    group_id: Mapped[int] = mapped_column(ForeignKey("volunteer_group.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    authorizer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    group_config_id: Mapped[int] = mapped_column(
        ForeignKey("group_config_version.id", ondelete="RESTRICT")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    configuration: Mapped[dict] = mapped_column(JSON)


class WeeklyInspectionExecution(TimestampMixin, Base):
    __tablename__ = "weekly_inspection_execution"
    __table_args__ = (
        UniqueConstraint("plan_id", "target_week", name="uq_weekly_execution_week"),
        Index("ix_weekly_execution_state", "status", "id"),
        CheckConstraint("target_week >= 1 AND target_week <= 60", name="week"),
        CheckConstraint(
            "status IN ('QUEUED','GENERATED','PREPARED','MISSED',"
            "'FAILED','NEEDS_REVIEW','CANCELED')",
            name="state",
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("weekly_inspection_plan.id", ondelete="RESTRICT")
    )
    plan_version: Mapped[int] = mapped_column(Integer)
    authorizer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    target_week: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DATETIME_3)
    date_from: Mapped[date] = mapped_column(DATE_COL)
    date_to: Mapped[date] = mapped_column(DATE_COL)
    configuration: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    reason_code: Mapped[str | None] = mapped_column(String(64))
    task_ids: Mapped[list] = mapped_column(JSON, default=list)
    assignment_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("assignment_confirmation_plan.id", ondelete="RESTRICT")
    )
    result_json: Mapped[dict | None] = mapped_column(JSON)
