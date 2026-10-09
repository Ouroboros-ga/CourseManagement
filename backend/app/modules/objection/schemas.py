"""异议域请求/响应模型（Pydantic 2.x）。

约定（技术方案 8.1，与 attendance/inspection 一致）：
- BIGINT 主键/外键对外统一以字符串（复用 academic.schemas 的 IdStr/OptIdStr）；
- 响应绝不直接返回 ORM 实体；日期时刻由 Pydantic 序列化为 ISO 字符串（UTC-naive）；
- desired_type / final_attendance_type 取考勤认定全集（含 NORMAL，漏报异常者可申诉改回正常）；
- 输入 file_ids 用 int 列表，服务端按上限与归属校验（见 service），关联前锁验文件仍 READY。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.academic.schemas import IdStr, OptIdStr

# 学生诉求 / 终审判定类型：考勤认定全集（技术方案 14，异议终审可改判任一类型含 NORMAL）。
ObjectionTypeLiteral = Literal["NORMAL", "LEAVE", "LATE", "ABSENT"]
ObjectionInitialStatusLiteral = Literal["PENDING", "PASSED", "REJECTED"]
ObjectionFinalStatusLiteral = Literal["PENDING", "APPROVED", "REJECTED"]


class ObjectionCreateRequest(BaseModel):
    """学生对本人某条考勤提交异议（POST /attendance/{id}/objections）。

    - desired_type：学生诉求的认定类型，必填；不得与当前认定相同（无意义申诉由 service 拒绝）；
    - reason：异议理由，选填、可审计；
    - file_ids：本人上传、READY、类别 OBJECTION_PROOF、未过期的证明材料（归属校验在 service）。
    """

    desired_type: ObjectionTypeLiteral
    reason: str = Field(default="", max_length=512)
    file_ids: list[int] = Field(default_factory=list, max_length=50)


class ObjectionInitialReviewRequest(BaseModel):
    """初核（POST /objections/{id}/initial-review）：PENDING→PASSED/REJECTED，不改考勤。

    comment 可空但建议填写；初核为参考意见，最终结论由终审形成（技术方案 14）。
    """

    decision: Literal["PASSED", "REJECTED"]
    comment: str | None = Field(default=None, max_length=512)


class ObjectionFinalReviewRequest(BaseModel):
    """终审（POST /objections/{id}/final-review）：PENDING→APPROVED/REJECTED。

    - APPROVED 须给出 final_type（终审判定类型）。若 final_type 与考勤当前认定一致，仅关闭
      异议不改考勤；若不一致则更正考勤并追加版本，此时须同时具备 attendance.correct；
    - REJECTED 不接受 final_type（维持原考勤），comment 记录驳回理由；
    - current_version 为审阅者所见考勤当前版本，与 base_attendance_version 一致性用于
      "不覆盖他人新认定"的判断（技术方案 14、15）。
    """

    decision: Literal["APPROVED", "REJECTED"]
    final_type: ObjectionTypeLiteral | None = None
    comment: str | None = Field(default=None, max_length=512)
    current_version: int = Field(ge=1)


class ObjectionStudentBrief(BaseModel):
    """异议发起学生的展示信息。"""

    student_id: IdStr
    student_no: str | None = None
    name: str | None = None
    administrative_class_name: str | None = None


class ObjectionTaskBrief(BaseModel):
    """异议所属查课任务与课程时段信息。"""

    task_id: IdStr
    inspection_date: date
    inspection_type: str
    course_name_snapshot: str | None = None
    class_name_snapshot: str | None = None
    classroom_snapshot: str | None = None
    start_period: int | None = None
    end_period: int | None = None
    period_text: str | None = None
    week_no: int | None = None


class ObjectionAttendanceBrief(BaseModel):
    """异议关联的考勤记录信息。"""

    id: IdStr
    task_id: IdStr
    student_id: IdStr
    effective_type: str
    current_version: int
    base_attendance_version: int


class ObjectionFileBrief(BaseModel):
    """异议证明材料文件信息。"""

    id: IdStr
    filename: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    access_url: str | None = None


class ObjectionResponse(BaseModel):
    """异议全貌：考勤锚点、发起版本、诉求、初核/终审状态与意见、终审改判、证明材料文件，附学生/任务/考勤完整上下文。"""

    id: IdStr
    attendance_record_id: IdStr
    student_id: IdStr
    base_attendance_version: int
    reason: str
    desired_type: ObjectionTypeLiteral
    initial_status: ObjectionInitialStatusLiteral
    initial_reviewed_by: OptIdStr
    initial_reviewed_at: datetime | None
    initial_comment: str | None
    final_status: ObjectionFinalStatusLiteral
    final_reviewed_by: OptIdStr
    final_reviewed_at: datetime | None
    final_comment: str | None
    final_attendance_type: ObjectionTypeLiteral | None
    file_ids: list[IdStr]
    created_at: datetime
    updated_at: datetime

    # 扩展结构化上下文（供移动端/Web端直接渲染）
    student: ObjectionStudentBrief | None = None
    task: ObjectionTaskBrief | None = None
    attendance: ObjectionAttendanceBrief | None = None
    files: list[ObjectionFileBrief] = Field(default_factory=list)

    # 平铺便利字段（无需前端多层解包）
    student_name: str | None = None
    student_no: str | None = None
    course_name: str | None = None
    class_name: str | None = None
    classroom: str | None = None
    inspection_date: str | None = None
    date: str | None = None
    period: str | None = None
    original_attendance_type: str | None = None
    current_attendance_type: str | None = None

    # 小程序模板特定绑定字段（零代码修改直接开箱生效）
    studentName: str | None = None
    studentId: str | None = None
    courseName: str | None = None
    type: str | None = None


__all__ = [
    "ObjectionTypeLiteral",
    "ObjectionInitialStatusLiteral",
    "ObjectionFinalStatusLiteral",
    "ObjectionCreateRequest",
    "ObjectionInitialReviewRequest",
    "ObjectionFinalReviewRequest",
    "ObjectionStudentBrief",
    "ObjectionTaskBrief",
    "ObjectionAttendanceBrief",
    "ObjectionFileBrief",
    "ObjectionResponse",
]

