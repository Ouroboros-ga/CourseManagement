"""指定课次地点覆盖与不可变变更链。

地点覆盖按稳定课次键（``s:{shared_meeting_key 或 schedule.id}|{日期}``）单独持久化，
不改写正式课表的原始导入来源；地点修订号独立于任务 lock_version 命名。变更链只追加
不重写：已完成任务的原始快照与历史报表不受影响。表结构在迁移
``f26a1017s004_occurrence_location`` 中建立（原规划名 s003 已被教职工导入目标迁移占用）。
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import (
    DATE_COL,
    DATETIME_3,
    Base,
    CreateTimeMixin,
    TimestampMixin,
    pk_column,
    utcnow,
)
from app.core.db import MYSQL_TABLE_ARGS


class OccurrenceLocationOverride(TimestampMixin, Base):
    """某稳定课次键的当前地点覆盖层；行不存在即无覆盖。

    任何院视图对同一真实课次（已确认共享 meeting）都读到同一行的 revision/location；
    生成与地点变更以本行为稳定课次锁。location 为 NULL 表示曾改后恢复为原始课表地点。
    """

    __tablename__ = "occurrence_location_override"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="occurrence_location_revision"),
        Index("ix_occurrence_location_school", "school_id", "occurrence_key"),
        MYSQL_TABLE_ARGS,
    )

    occurrence_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"))
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    effective_date: Mapped[date] = mapped_column(DATE_COL)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )


class OccurrenceLocationChange(CreateTimeMixin, Base):
    """地点变更历史（append-only）：previous_location 为 NULL 表示原始课表地点。"""

    __tablename__ = "occurrence_location_change"
    __table_args__ = (
        CheckConstraint("revision_no >= 1", name="occurrence_location_change_revision"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    occurrence_key: Mapped[str] = mapped_column(String(128), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_location: Mapped[str | None] = mapped_column(String(128))
    new_location: Mapped[str | None] = mapped_column(String(128))
    effective_date: Mapped[date] = mapped_column(DATE_COL)
    changed_at: Mapped[datetime] = mapped_column(DATETIME_3, default=utcnow)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(512))


__all__ = [
    "OccurrenceLocationOverride",
    "OccurrenceLocationChange",
]
