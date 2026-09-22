"""统计/周报域请求/响应模型（Pydantic 2.x）。

约定（技术方案 8.1，与 attendance/objection 一致）：
- BIGINT 主键/外键对外统一以字符串（复用 academic.schemas 的 IdStr）；
- 响应绝不返回 ORM 实体；统计指标为聚合值，比率以 float 表达，缺分母时为 null；
- statistics_available：该维度分母（有效应到）≤ 0 时为 false 且比率字段为 null，
  不显示 0%/100%（技术方案 17 第 552 行）。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.academic.schemas import IdStr

AttendanceTypeLiteral = Literal["NORMAL", "LEAVE", "LATE", "ABSENT"]
# 与技术方案 17：未完成两指标互不混用。currentStatus=当前状态派生；
# deadlineAssessment=截止时点快照（VALID_SUBMISSION/OVERDUE_UNEXECUTED/CANCELED，未到期 null）。
DeadlineAssessmentLiteral = Literal["VALID_SUBMISSION", "OVERDUE_UNEXECUTED", "CANCELED"]


class AttendanceStatsQuery(BaseModel):
    """GET /statistics/attendance 入参：学期必填，周次或日期区间二选一。

    - semester_id 必填（考勤随任务归属学期，聚合以学期为轴，技术方案 9.2）；
    - week_no 与 (date_from,date_to) 二者恰选其一作为时间窗；均缺则报 422（避免全表无界聚合）。
    """

    semester_id: int = Field(ge=1)
    week_no: int | None = Field(default=None, ge=1)
    date_from: date_type | None = None
    date_to: date_type | None = None

    @model_validator(mode="after")
    def _check_window(self) -> AttendanceStatsQuery:
        has_week = self.week_no is not None
        has_range = self.date_from is not None or self.date_to is not None
        if has_week and has_range:
            raise ValueError("week_no 与 date_from/date_to 不可同时提供")
        if not has_week and not has_range:
            raise ValueError("须提供 week_no 或 date_from/date_to 作为统计时间窗")
        if has_range and (self.date_from is None or self.date_to is None):
            raise ValueError("日期区间须同时提供 date_from 与 date_to")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from 不得晚于 date_to")
        return self


class OverallStats(BaseModel):
    """全院（命中范围内所有符合条件任务）合计指标。先累加分子分母再相除。"""

    statistics_available: bool
    expected_count: int  # 有效应到：Σ task.expected_count_current
    abnormal_count: int  # Σ 非 NORMAL 当前考勤
    normal_count: int
    leave_count: int
    late_count: int
    absent_count: int
    abnormal_rate: float | None  # abnormal/expected；expected≤0→null 且 available=false


class ClassStatsItem(BaseModel):
    """单班级指标（按任务名单快照 class_name_snapshot 归并，技术方案 17 第 554 行）。

    excluded_task_count：因人工只调整总应到数、无分班明细可推导而被剔除出班级比例的任务数，
    不均摊、不臆造分母（技术方案 17 第 554 行）。
    """

    class_name: str
    expected_count: int
    abnormal_count: int
    normal_count: int
    leave_count: int
    late_count: int
    absent_count: int
    abnormal_rate: float | None
    class_ratio_available: bool
    excluded_task_count: int


class TaskStatsItem(BaseModel):
    """单任务聚合明细（可选 include_tasks=true 时返回）。"""

    task_id: IdStr
    inspection_date: date_type
    week_no: int
    expected_count: int
    abnormal_count: int
    expected_count_adjusted: bool  # 当前应到≠初始快照
    class_ratio_available: bool


class AttendanceStatsResponse(BaseModel):
    """统计口径输出（技术方案 17）：仅审核通过且未取消任务的当前有效考勤。

    待审核异常不计入正式缺勤（无 APPROVED 提交者不进 eligible_task_count 与各项聚合）。
    """

    semester_id: IdStr
    week_no: int | None
    date_from: date_type | None
    date_to: date_type | None
    eligible_task_count: int  # 命中范围内"已审核通过且未取消"的任务数
    overall: OverallStats
    classes: list[ClassStatsItem]
    tasks: list[TaskStatsItem] | None = None


class IncompleteTaskItem(BaseModel):
    """未完成清单一行：同时输出当前状态与截止时快照，二者不混名（技术方案 17 第 470 行）。

    - current_incomplete：当前无审核通过提交且未取消 → True（当前状态派生）；
    - deadline_assessment：截止时点既成事实快照，未到期为 null（技术方案 13.3）；
    - 两者语义不同：晚到补交并审核通过后 current_incomplete=False，但 deadline_assessment
      仍保留 OVERDUE_UNEXECUTED，记录"当初截止时未执行"。
    """

    task_id: IdStr
    inspection_date: date_type
    week_no: int
    class_name_snapshot: str | None
    course_name_snapshot: str | None
    current_incomplete: bool
    deadline_assessment: DeadlineAssessmentLiteral | None
    deadline_at: str | None  # ISO 字符串（快照截止时刻）
    assignee_user_id: IdStr | None  # 截止时受派人快照


class IncompleteTasksResponse(BaseModel):
    """分页未完成清单：区分"当前未完成"与"截止时未完成"，支持分别计数。"""

    semester_id: IdStr
    week_no: int | None
    date_from: date_type | None
    date_to: date_type | None
    current_incomplete_count: int  # 当前未完成总数（未取消且无 APPROVED 提交）
    overdue_unexecuted_count: int  # 截止时逾期未执行总数（快照事实）
    items: list[IncompleteTaskItem]
    page: int
    page_size: int
    total: int


__all__ = [
    "AttendanceTypeLiteral",
    "DeadlineAssessmentLiteral",
    "AttendanceStatsQuery",
    "OverallStats",
    "ClassStatsItem",
    "TaskStatsItem",
    "AttendanceStatsResponse",
    "IncompleteTaskItem",
    "IncompleteTasksResponse",
]
