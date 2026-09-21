"""导入批次 ORM：承载"预览→确认"两步之间的暂存态（技术方案 19、PERMISSIONS.md 12.5）。

设计要点：
- 预览阶段把文件解析为**规范行**存入 payload_json，并把错误/告警存 error_json、
  概要存 summary_json；确认阶段不再依赖原始文件，只用 payload_json 重新校验外部引用
  是否仍存在，再**整批原子**落库（同事务，任一行失败全回滚）。
- 批次有有效期（expires_at）：超时未确认置 EXPIRED，防暂存数据长期滞留。
- 归属学期 / 教学班按 target 需要填充（roster→teaching_class；timetable/volunteer→semester）。
- target / status 以稳定字符串存储并加 CHECK，不映射 MySQL 原生 ENUM。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class ImportTarget(enum.StrEnum):
    ROSTER = "roster"  # 教学班名单（受 student.manage 守卫）
    TIMETABLE = "timetable"  # 课表 / 教学班基础（受 academic.manage 守卫）
    VOLUNTEER = "volunteer"  # 志愿者学期资格（受 volunteer.manage 守卫）


class ImportBatchStatus(enum.StrEnum):
    PREVIEW = "PREVIEW"  # 已解析暂存，等待确认
    CONFIRMED = "CONFIRMED"  # 已整批落库
    FAILED = "FAILED"  # 确认时校验/写入失败（已回滚）
    EXPIRED = "EXPIRED"  # 预览暂存超时作废


_ALLOWED_TARGET = "('roster','timetable','volunteer')"
_ALLOWED_STATUS = "('PREVIEW','CONFIRMED','FAILED','EXPIRED')"


class ImportBatch(TimestampMixin, Base):
    """一次导入的暂存批次。明文文件不入库，只存解析后的规范结构与统计。"""

    __tablename__ = "import_batch"
    __table_args__ = (
        CheckConstraint(f"target IN {_ALLOWED_TARGET}", name="ck_import_batch_target"),
        CheckConstraint(f"status IN {_ALLOWED_STATUS}", name="ck_import_batch_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ImportBatchStatus.PREVIEW.value,
        server_default="'PREVIEW'",
    )
    semester_id: Mapped[int | None] = mapped_column(
        ForeignKey("semester.id", ondelete="SET NULL")
    )
    teaching_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("teaching_class.id", ondelete="SET NULL")
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    filename: Mapped[str | None] = mapped_column(String(255))
    # 解析后的规范行（供确认阶段重放），以及预览概要、结构化错误/告警。
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    error_json: Mapped[list | None] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
