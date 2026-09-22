"""考勤域请求/响应模型（Pydantic 2.x）。

约定（技术方案 8.1、与 academic/inspection 一致）：
- BIGINT 主键/外键对外统一以字符串（复用 academic.schemas 的 IdStr/OptIdStr）；
- 响应绝不直接返回 ORM 实体；日期时刻由 Pydantic 序列化为 ISO 字符串（UTC-naive）；
- effective_type 为当前认定（NORMAL/LEAVE/LATE/ABSENT），current_version 为乐观锁与
  "更正不覆盖他人新认定"的版本锚点（技术方案 14、15）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.academic.schemas import IdStr, OptIdStr

# 考勤认定类型（含 NORMAL）：更正可把某生改判为任一类型（含更正漏报异常，技术方案 12/14）。
AttendanceTypeLiteral = Literal["NORMAL", "LEAVE", "LATE", "ABSENT"]
# 版本来源类型：审核生成 / 管理员更正 / 异议终审（技术方案 14，异议终审随 P6 落地）。
AttendanceSourceLiteral = Literal["SUBMISSION", "CORRECTION", "OBJECTION_FINAL"]


class AttendanceTaskBrief(BaseModel):
    """考勤所属查课任务的精简展示信息（列表按任务上下文回看，技术方案 14）。"""

    task_id: IdStr
    inspection_date: date
    inspection_type: str
    course_name_snapshot: str | None
    class_name_snapshot: str | None


class AttendanceResponse(BaseModel):
    """当前有效考勤：一任务一学生一条，附学生快照与任务上下文。"""

    id: IdStr
    task_id: IdStr
    student_id: IdStr
    student_no: str | None
    name: str | None
    effective_type: AttendanceTypeLiteral
    current_version: int
    source_submission_item_id: OptIdStr
    task: AttendanceTaskBrief | None
    created_at: datetime


class AttendanceVersionResponse(BaseModel):
    """考勤历史版本（不可变事实）：每次生成/更正/异议终审追加一条（技术方案 14）。"""

    id: IdStr
    attendance_record_id: IdStr
    version_no: int
    attendance_type: AttendanceTypeLiteral
    source_type: AttendanceSourceLiteral
    source_id: OptIdStr
    changed_by: OptIdStr
    reason: str | None
    created_at: datetime


class AttendanceCorrectionRequest(BaseModel):
    """更正最终考勤：改当前认定并追加版本，不重写原提交与既往版本（技术方案 14）。

    current_version 为客户端所见版本，服务端以条件更新校验；不符即 409 VERSION_CONFLICT，
    提示刷新后重看，绝不覆盖他人的新认定（技术方案 15）。reason 必填、可审计。
    """

    attendance_type: AttendanceTypeLiteral
    reason: str = Field(min_length=1, max_length=512)
    current_version: int = Field(ge=1)


__all__ = [
    "AttendanceTypeLiteral",
    "AttendanceSourceLiteral",
    "AttendanceTaskBrief",
    "AttendanceResponse",
    "AttendanceVersionResponse",
    "AttendanceCorrectionRequest",
]
