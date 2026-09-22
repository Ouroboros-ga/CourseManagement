"""统计/版本化周报域 ORM 模型（技术方案 9.4、17、18）。

W7a（统计只读）无新表；W7b 起新增报表源修订基础设施；W7c 新增版本化周报两表：

- report_source_revision：定位「某学期某周的考勤源数据被改动过几次」，用于周报落后判定。
  联合主键 (semester_id, week_no)，无自增 id；revision 为源数据修订号，凡影响考勤事实的写
  路径在同一事务内原子 +1（见 source_revision.bump）。它是"是否落后于源数据"的技术指针，
  非业务冻结态；不承载个人考勤明细，故无保留期约束。
- report：周报主记录（技术方案 18）。以 (semester_id, week_no, scope) 联合唯一标识一份
  逻辑周报；只存"最新版本指针"（latest_version_no / latest_updated_at），可变，随发布更新。
- report_version：不可覆盖的版本化快照（技术方案 9.4、18）。每次生成登记一个 version_no
  单调递增、只追加不原地改；记录生成时读到的 source_revision 与 rule/template 版本，供落后
  与"公式/模板已更新"提示；产物文件（明细 JSON 快照 + Excel）以独立类别文件对象归档，
  配独立保留期限（不复用照片/临时清理规则）。状态机 GENERATING → PUBLISHED / FAILED，
  attempt_token 为中断接管令牌（并发/迟到重复发布防护）。

约定（技术方案 8.1、9，与 identity/academic/inspection 模块一致）：
- 学期外键 RESTRICT 保留历史完整；周次为学期内正整数；
- 枚举以字符串值存储并加 CHECK；BIGINT 数值列防长期累积溢出；
- report 用 TimestampMixin（指针可变），report_version 用 CreateTimeMixin（版本不可变）；
- 文件产物外键 SET NULL：即便文件行被物理移除（V1.0 清理仅置 PURGED 保留行，实际不删），
  版本事实行仍作为审计留存，不被级联抹除。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import (
    DATETIME_3,
    Base,
    CreateTimeMixin,
    TimestampMixin,
    pk_column,
    utcnow,
)
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


# --------------------------------------------------------------------------- #
# 版本化周报（W7c，技术方案 18）
# --------------------------------------------------------------------------- #
class ReportVersionStatus(enum.StrEnum):
    """周报版本状态机：登记 → 发布 / 失败。仅 PUBLISHED 版本可对外呈现/下载。"""

    GENERATING = "GENERATING"  # 已分配版本号、正在一致性读取与产物生成中（可被接管重试）
    PUBLISHED = "PUBLISHED"  # 已成功落文件并发布，不可覆盖
    FAILED = "FAILED"  # 生成失败（如产物写入异常）；保留行以审计，占位版本号不复用


_REPORT_VERSION_STATUSES = "('GENERATING','PUBLISHED','FAILED')"
# V1.0 仅学院级聚合周报；CLASS 预留为后续按班级出报的收敛位（不硬编码业务口径）。
_REPORT_SCOPES = "('COLLEGE','CLASS')"


class Report(TimestampMixin, Base):
    """周报主记录：一份逻辑周报（学期 × 周次 × 范围）一行，存最新版本指针。"""

    __tablename__ = "report"
    __table_args__ = (
        CheckConstraint(f"scope IN {_REPORT_SCOPES}", name="ck_report_scope"),
        CheckConstraint("week_no >= 1", name="ck_report_week"),
        CheckConstraint("latest_version_no >= 0", name="ck_report_latest_version"),
        UniqueConstraint("semester_id", "week_no", "scope", name="uq_report_sem_week_scope"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semester.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="COLLEGE", server_default=text("'COLLEGE'")
    )
    # 最新版本指针（非事实来源，事实以 report_version 为准）：界面显示"最新版本更新时间"。
    latest_version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    latest_updated_at: Mapped[datetime | None] = mapped_column(DATETIME_3)


class ReportVersion(CreateTimeMixin, Base):
    """版本化周报快照：一次生成一行，version_no 单调递增、不可覆盖。"""

    __tablename__ = "report_version"
    __table_args__ = (
        CheckConstraint(f"status IN {_REPORT_VERSION_STATUSES}", name="ck_report_version_status"),
        CheckConstraint("source_revision >= 0", name="ck_report_version_source_revision"),
        CheckConstraint("version_no >= 1", name="ck_report_version_no"),
        UniqueConstraint("report_id", "version_no", name="uq_report_version_report_no"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    report_id: Mapped[int] = mapped_column(
        ForeignKey("report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 生成时读到的源数据修订号；与 report_source_revision.revision 比较即得"是否落后源数据"。
    source_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    # 生成时生效的统计公式版本与 Excel 模板版本（均来自 Settings，可配、不硬编码）。
    rule_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    template_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # 产物文件（明细 JSON 快照 + Excel），独立类别文件对象归档；SET NULL 保版本事实不被级联抹除。
    snapshot_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_object.id", ondelete="SET NULL")
    )
    excel_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_object.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReportVersionStatus.GENERATING.value,
        server_default=text("'GENERATING'"),
        index=True,
    )
    # 中断接管令牌：发布时以 (id, status=GENERATING, attempt_token=?) 条件更新，防迟到重复发布。
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    generated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    generated_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    reason: Mapped[str | None] = mapped_column(String(512))


__all__ = [
    "ReportSourceRevision",
    "ReportVersionStatus",
    "Report",
    "ReportVersion",
]
