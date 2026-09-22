"""异议域 ORM 模型（技术方案 9.3、14、15；PERMISSIONS.md 8）。

覆盖"学生对本人考勤的异议 + 异议证明材料关联"两张表：

- objection        一条异议锚定一条考勤记录（attendance_record_id）与发起学生（student_id
                   冗余以便本人范围与防枚举过滤），记录发起时的考勤版本 base_attendance_version
                   作为"终审更正不得覆盖他人新认定"的版本锚点；desired_type 为学生诉求，
                   初核/终审各带状态、处理人、时刻与意见。初核为参考不改考勤，终审通过且
                   需更正时在同一事务改判考勤并追加版本（技术方案 14）。final_status=PENDING
                   视为"未完成异议"，用于并发下同一考勤只允许一个进行中异议（技术方案 15）。
- objection_file   异议与证明材料文件的联合主键关联（objection_id + file_id）。文件行
                   RESTRICT——被未完成异议引用的材料在异议关闭前不得物理清理，与到期清理
                   按同一文件锁协议串行化（技术方案 16.3、538/713）。

约定（技术方案 8.1、9，与 attendance/inspection 一致）：
- 枚举以稳定字符串值存储并加 CHECK，不映射 MySQL 原生 ENUM；
- 随考勤级联（考勤记录随任务删除而亡，异议随之消亡）；对学生 / 账号等主数据用 RESTRICT /
  SET NULL 保留历史完整；考勤记录删除路径与任务级联一致；
- objection 可变（状态流转）故用 TimestampMixin（created_at + updated_at）；
- source/关联多态引用不建外键的字段此处无（终审判定类型直接落 final_attendance_type）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class ObjectionInitialStatus(enum.StrEnum):
    """异议初核状态（技术方案 14）。初核意见为参考，不直接改考勤。

    PENDING=待初核；PASSED=初核通过（建议终审支持）；REJECTED=初核拒绝（仍由教师终审形成
    最终结论）。无负责人持初核权限时，教师可直接终审、初核状态停留 PENDING（技术方案 14）。
    """

    PENDING = "PENDING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class ObjectionFinalStatus(enum.StrEnum):
    """异议终审状态（技术方案 14）。final_status=PENDING 即"未完成异议"。

    APPROVED=终审通过（如与当前考勤不一致则同事务更正考勤并追加 OBJECTION_FINAL 版本）；
    REJECTED=终审驳回（不改考勤）。
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# 诉求 / 终审判定类型均取自考勤认定全集（含 NORMAL：漏报异常者可申诉改回正常）。
_OBJECTION_TYPE_DOMAIN = "('NORMAL','LEAVE','LATE','ABSENT')"
_INITIAL_STATUSES = "('PENDING','PASSED','REJECTED')"
_FINAL_STATUSES = "('PENDING','APPROVED','REJECTED')"


class Objection(TimestampMixin, Base):
    """学生对本人某条考勤的异议（技术方案 9.3、14）。

    学生只能针对本人记录提交，记录发起时考勤版本（base_attendance_version）。锁定考勤记录后
    检查同一记录是否已有 final_status=PENDING 的未完成异议，保证并发下只创建一个（技术方案 15）。
    终审通过且需更正时，在同一事务更新异议、考勤当前值、考勤版本、审计（报表源修订号留 P7
    统一施加）；若考勤版本已与发起时不同，返回 VERSION_CONFLICT，不覆盖他人新认定（技术方案 14）。
    """

    __tablename__ = "objection"
    __table_args__ = (
        CheckConstraint(
            f"desired_type IN {_OBJECTION_TYPE_DOMAIN}",
            name="ck_objection_desired_type",
        ),
        CheckConstraint(
            f"final_attendance_type IS NULL OR final_attendance_type IN {_OBJECTION_TYPE_DOMAIN}",
            name="ck_objection_final_attendance_type",
        ),
        CheckConstraint(
            f"initial_status IN {_INITIAL_STATUSES}", name="ck_objection_initial_status"
        ),
        CheckConstraint(f"final_status IN {_FINAL_STATUSES}", name="ck_objection_final_status"),
        # 未完成异议（final_status=PENDING）按考勤查重、待办队列读取的热点过滤。
        Index("ix_objection_attendance_final_status", "attendance_record_id", "final_status"),
        Index("ix_objection_student_id", "student_id"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    attendance_record_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_record.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 发起学生（= 该考勤记录的学生），冗余以支撑 OWN_OBJECTION 范围与防枚举过滤（技术方案 9.3）。
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), nullable=False
    )
    # 发起时所见的考勤当前版本：终审更正的版本一致性锚点（技术方案 14）。
    base_attendance_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    desired_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # 初核（参考意见，不改考勤）。
    initial_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ObjectionInitialStatus.PENDING.value,
        server_default=text("'PENDING'"),
    )
    initial_reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    initial_reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    initial_comment: Mapped[str | None] = mapped_column(String(512))

    # 终审（形成最终结论；通过且不一致时改判考勤）。
    final_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ObjectionFinalStatus.PENDING.value,
        server_default=text("'PENDING'"),
    )
    final_reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    final_reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    final_comment: Mapped[str | None] = mapped_column(String(512))
    # 终审通过后的认定（= 实际写入考勤的类型或维持不变的类型）；未终审时为空。
    final_attendance_type: Mapped[str | None] = mapped_column(String(16))

    files: Mapped[list[ObjectionFile]] = relationship(
        back_populates="objection", cascade="all, delete-orphan", lazy="selectin"
    )


class ObjectionFile(Base):
    """异议与证明材料文件的关联（技术方案 9.3：objection_id + file_id 联合主键）。

    仅 READY、本人上传、类别为 OBJECTION_PROOF、未过期的文件可关联（校验在 service，与提交
    附件同规）。文件行 RESTRICT：被未完成异议引用的材料在异议关闭前不得被到期清理误删，
    清理与新建引用按同一文件行锁协议串行化（技术方案 16.3）。
    """

    __tablename__ = "objection_file"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    objection_id: Mapped[int] = mapped_column(
        ForeignKey("objection.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("file_object.id", ondelete="RESTRICT"), primary_key=True
    )

    objection: Mapped[Objection] = relationship(back_populates="files")


__all__ = [
    "ObjectionInitialStatus",
    "ObjectionFinalStatus",
    "Objection",
    "ObjectionFile",
]
