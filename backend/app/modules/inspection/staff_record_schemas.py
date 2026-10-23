"""教职工查课卡片、明细、统计与导出数据模型。

遵循三 Tab 规划与架构合同：
- task_id, attendance_record_id, student_id 等统一以字符串返回，避免 JS 截断 BIGINT；
- 统计口径按视图收窄；责任视图标明仅统计负责班级；未形成正式考勤 counts 为 null。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ViewLiteral = Literal["teaching", "responsible"]


class CollegeBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class StaffCardScope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    view: ViewLiteral
    count_basis: str = Field(description="统计口径说明，如 AUTHORIZED_STUDENT_SET")


class AttendanceCounts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int = 0
    NORMAL: int = 0
    LEAVE: int = 0
    LATE: int = 0
    ABSENT: int = 0


class StaffInspectionRecordCard(BaseModel):
    """教工查课任务卡片。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    teaching_class_id: str | None = None
    occurrence_key: str
    course_name: str
    class_name_snapshot: str | None = None
    responsible_college: CollegeBrief
    inspection_date: str
    starts_at: str | None = None
    time_basis: str = "PERIODS"
    time_label: str | None = None
    ends_at: str | None = None
    start_period: int | None = None
    end_period: int | None = None
    classroom: str | None = None
    location_revision: str | None = None
    # 执行异常独立于学生考勤；不伪造 RECORDED。
    attendance_state: str  # RECORDED / PENDING_SUBMISSION / PENDING_REVIEW / CANCELED / EXCEPTION
    scope: StaffCardScope
    counts: AttendanceCounts | None = None
    allowed_actions: list[str] = Field(default_factory=lambda: ["view_detail"])


class StaffInspectionRecordListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[StaffInspectionRecordCard]
    total: int
    page: int
    page_size: int


class StaffStudentAttendanceItem(BaseModel):
    """卡片内受权学生考勤明细。"""

    model_config = ConfigDict(extra="ignore")

    attendance_record_id: str
    task_id: str
    student_id: str
    student_no: str
    name: str
    administrative_class_name_snapshot: str | None = None
    effective_type: str
    current_version: int
    photo_file_ids: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    restriction_reason: str | None = None


class StaffStudentAttendanceListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[StaffStudentAttendanceItem]
    total: int
    page: int
    page_size: int


class StaffCollegeSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    college_id: str
    college_name: str
    task_count: int
    student_counts: AttendanceCounts


class StaffInspectionSummaryResponse(BaseModel):
    """同范围汇总统计响应。"""

    model_config = ConfigDict(extra="ignore")

    view: ViewLiteral
    scope_description: str
    task_count: int
    recorded_task_count: int
    unrecorded_task_count: int
    student_counts: AttendanceCounts
    college_summaries: list[StaffCollegeSummary] = Field(default_factory=list)


__all__ = [
    "ViewLiteral",
    "CollegeBrief",
    "StaffCardScope",
    "AttendanceCounts",
    "StaffInspectionRecordCard",
    "StaffInspectionRecordListResponse",
    "StaffStudentAttendanceItem",
    "StaffStudentAttendanceListResponse",
    "StaffCollegeSummary",
    "StaffInspectionSummaryResponse",
]
