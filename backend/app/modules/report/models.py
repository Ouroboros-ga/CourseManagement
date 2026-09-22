"""统计/版本化周报域 ORM 模型（技术方案 9.4、17）。

W7a（统计只读）无新表；W7b 起新增报表源修订基础设施：

- report_source_revision：定位「某学期某周的考勤源数据被改动过几次」，用于周报落后判定。
  联合主键 (semester_id, week_no)，无自增 id；revision 为源数据修订号，凡影响考勤事实的写
  路径在同一事务内原子 +1（见 source_revision.bump）。它是"是否落后于源数据"的技术指针，
  非业务冻结态；不承载个人考勤明细，故无保留期约束。

约定（技术方案 8.1、9，与 identity/academic/inspection 模块一致）：
- 学期外键 RESTRICT 保留历史完整；周次为学期内正整数；
- updated_at 记录最近一次递增时刻（DATETIME(3) UTC）；
- 枚举以字符串值存储的约束本表暂无（仅一数值列 + 时间戳）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, utcnow
from app.core.db import MYSQL_TABLE_ARGS


class ReportSourceRevision(Base):
    """(学期, 周次) → 考勤源数据修订号。联合主键，同事务原子递增，供周报落后判定。"""

    __tablename__ = "report_source_revision"
    __table_args__ = (
        CheckConstraint(
            "revision >= 0",
            name="ck_report_source_revision_nonneg",
        ),
        CheckConstraint(
            "week_no >= 1",
            name="ck_report_source_revision_week",
        ),
        MYSQL_TABLE_ARGS,
    )

    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), primary_key=True
    )
    week_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 修订号：首建即 1（表示已发生一次源变更），其后每次 bump +1；BIGINT 防长期溢出。
    revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME_3, nullable=False, default=utcnow, onupdate=utcnow
    )


__all__ = ["ReportSourceRevision"]
