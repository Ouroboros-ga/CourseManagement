"""考勤域 ORM 模型（技术方案 9.3、12、14、15）。

覆盖"当前有效考勤 + 历史版本"两张表：

- attendance_record         当前有效考勤：一任务一学生一条（task_id+student_id 联合唯一），
                            审核通过时为该名单版本每名学生建立初始记录（未列异常者 NORMAL，
                            技术方案 12）；effective_type 为当前认定，current_version 为乐观锁
                            与"更正不覆盖他人新认定"的版本校验锚点，source_submission_item_id
                            指向据以生成的异常明细（NORMAL 行为空）；
- attendance_record_version 考勤历史版本：每次生成 / 更正 / 异议终审追加一条不可变版本，
                            (attendance_record_id, version_no) 联合唯一，记录认定、来源类型与
                            来源主键、变更人与原因。改的是"当前认定"并"追加版本"，不重写原
                            提交与既往版本（技术方案 14）。

约定（技术方案 8.1、9 与 identity/academic/inspection 一致）：
- 枚举以稳定字符串值存储并加 CHECK，不映射 MySQL 原生 ENUM；
- 随任务级联（任务删除则考勤历史随其消亡），对学生 / 账号等主数据用 RESTRICT / SET NULL
  保留历史完整；考勤版本、异常明细来源为多态引用（source_id 不建外键），避免跨表强约束耦合。
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, CreateTimeMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class AttendanceType(enum.StrEnum):
    """考勤认定类型（技术方案 12、14）。NORMAL=正常，其余为异常。

    提交异常明细只会出现 LEAVE/LATE/ABSENT；attendance_record.effective_type 可为 NORMAL
    （审核通过时未列异常的学生）。异议终审可把某生改判为任一类型（含更正漏报异常）。
    """

    NORMAL = "NORMAL"
    LEAVE = "LEAVE"
    LATE = "LATE"
    ABSENT = "ABSENT"


class AttendanceSourceType(enum.StrEnum):
    """考勤版本来源类型（技术方案 14）。多态：source_id 指向各来源表主键，不建外键。"""

    SUBMISSION = "SUBMISSION"  # 审核通过初始生成：source_id = 异常明细 id（NORMAL 为空）
    CORRECTION = "CORRECTION"  # 管理员更正：source_id = 更正所属 attendance_record.id
    OBJECTION_FINAL = "OBJECTION_FINAL"  # 异议终审更正：source_id = objection.id（P6）


_ATTENDANCE_TYPES = "('NORMAL','LEAVE','LATE','ABSENT')"
_ATTENDANCE_SOURCE_TYPES = "('SUBMISSION','CORRECTION','OBJECTION_FINAL')"


# --------------------------------------------------------------------------- #
# 当前有效考勤
# --------------------------------------------------------------------------- #
class AttendanceRecord(CreateTimeMixin, Base):
    """某任务某学生的当前有效考勤。

    审核通过时按提交所用名单版本为每名学生建立（技术方案 12）：listed 异常者取明细类型，
    未列者取 NORMAL，从而把"全部正常"与"未提交"清晰区分。后续更正修改 effective_type 并
    追加 attendance_record_version，不重写原提交。current_version 用于乐观锁与异议终审的
    "版本落后即业务冲突"判断（技术方案 14、15）。
    """

    __tablename__ = "attendance_record"
    __table_args__ = (
        UniqueConstraint("task_id", "student_id", name="uq_attendance_record_task_stu"),
        CheckConstraint(
            f"effective_type IN {_ATTENDANCE_TYPES}",
            name="ck_attendance_record_effective_type",
        ),
        CheckConstraint(
            "current_version >= 1", name="ck_attendance_record_current_version"
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    effective_type: Mapped[str] = mapped_column(String(16), nullable=False)
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # 据以生成的异常明细（NORMAL 行为空）；明细随提交级联删除时置空，保留考勤本身。
    source_submission_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("submission_abnormal_item.id", ondelete="SET NULL")
    )

    versions: Mapped[list[AttendanceRecordVersion]] = relationship(
        back_populates="record", cascade="all, delete-orphan", lazy="selectin"
    )


class AttendanceRecordVersion(CreateTimeMixin, Base):
    """考勤历史版本（不可变事实）。

    每次"生成 / 更正 / 异议终审"为当前认定追加一个 version_no（技术方案 14）；版本行只读
    不改写，报表与详情可回看每一步认定及其来源。source_type + source_id 多态指向来源记录。
    """

    __tablename__ = "attendance_record_version"
    __table_args__ = (
        UniqueConstraint(
            "attendance_record_id", "version_no", name="uq_attendance_record_version_rec_no"
        ),
        CheckConstraint(
            f"attendance_type IN {_ATTENDANCE_TYPES}",
            name="ck_attendance_record_version_type",
        ),
        CheckConstraint(
            f"source_type IN {_ATTENDANCE_SOURCE_TYPES}",
            name="ck_attendance_record_version_source_type",
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_record.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(512))

    record: Mapped[AttendanceRecord] = relationship(back_populates="versions")


__all__ = [
    "AttendanceType",
    "AttendanceSourceType",
    "AttendanceRecord",
    "AttendanceRecordVersion",
]
