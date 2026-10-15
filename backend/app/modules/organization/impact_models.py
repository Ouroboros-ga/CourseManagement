"""Configuration impact is a durable work item; original facts stay immutable."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class ConfigurationImpactItem(TimestampMixin, Base):
    __tablename__ = "configuration_impact_item"
    __table_args__ = (
        UniqueConstraint("college_id", "source_kind", "source_id", "source_version", "task_id", name="uq_configuration_impact_task"),
        CheckConstraint("status IN ('OPEN','KEEP','CANCEL','REASSIGNED')", name="ck_configuration_impact_status"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("inspection_task.id", ondelete="RESTRICT"), index=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    decision: Mapped[dict | None] = mapped_column(JSON)
