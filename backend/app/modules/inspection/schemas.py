"""查课任务与排班模块的请求/响应模型（Pydantic 2.x）。

约定（技术方案 8.1、与 academic/importer 一致）：
- 请求体字段沿用 snake_case；BIGINT 主键/外键对外统一以字符串（复用 academic.schemas
  的 IdStr/OptIdStr，构造接受 int 或 str）。
- 响应绝不直接返回 ORM 实体；日期由 Pydantic 序列化为 ISO 字符串，时刻为 UTC-naive。
- 当前状态 status 为服务端派生只读字段（五种：待执行/待审核/已完成/已逾期/已取消），
  计算依据来自任务本身 + 受派 + 提交/截止事实（Wave 2 仅用取消占位，Wave 3c 精化）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.academic.schemas import IdStr, OptIdStr

InspectionTypeLiteral = Literal["COURSE", "MORNING_STUDY", "EVENING_STUDY"]


# --------------------------------------------------------------------------- #
# 生成请求（预览 / 生成共用同一选择条件，两步无状态：确认即以前次预览结果为准）
# --------------------------------------------------------------------------- #
class InspectionGenerateRequest(BaseModel):
    """任务生成/预览的选择条件。

    日期维度：week_nos 与 (date_from/date_to) 至少给其一，否则 422；两者可并用以取并集。
    目标维度：COURSE 用 teaching_class_ids（据此定位该教学班的全部课表条目）；
    MORNING_STUDY / EVENING_STUDY 用 administrative_class_ids + 显式 start/end 节次。
    """

    semester_id: int = Field(ge=1)
    inspection_type: InspectionTypeLiteral
    week_nos: list[int] | None = Field(default=None, max_length=70)
    date_from: date | None = None
    date_to: date | None = None
    teaching_class_ids: list[int] | None = None
    administrative_class_ids: list[int] | None = None
    start_period: int | None = Field(default=None, ge=1, le=20)
    end_period: int | None = Field(default=None, ge=1, le=20)
    require_photo: bool = False
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _check_selection(self) -> InspectionGenerateRequest:
        has_weeks = bool(self.week_nos)
        has_dates = self.date_from is not None and self.date_to is not None
        if not has_weeks and not has_dates:
            raise ValueError("week_nos 与 date_from/date_to 至少提供其一")
        if has_dates and self.date_to < self.date_from:  # type: ignore[operator]
            raise ValueError("date_to 不得早于 date_from")
        if self.inspection_type == "COURSE":
            if not self.teaching_class_ids:
                raise ValueError("课程查课必须提供 teaching_class_ids")
        else:
            if not self.administrative_class_ids:
                raise ValueError("自习查课必须提供 administrative_class_ids")
            if self.start_period is None or self.end_period is None:
                raise ValueError("自习查课必须提供 start_period 与 end_period")
            if self.end_period < self.start_period:
                raise ValueError("end_period 不得早于 start_period")
        if self.week_nos is not None and any(w < 1 or w > 60 for w in self.week_nos):
            raise ValueError("周次须在 1..60 范围内")
        return self


# --------------------------------------------------------------------------- #
# 任务视图
# --------------------------------------------------------------------------- #
InspectionTaskStatus = Literal["待执行", "待审核", "已完成", "已逾期", "已取消"]


class TaskAssignmentBrief(BaseModel):
    volunteer_user_id: IdStr
    assign_method: str


DeadlineAssessmentResultLiteral = Literal[
    "VALID_SUBMISSION", "OVERDUE_UNEXECUTED", "CANCELED"
]


class DeadlineAssessmentBrief(BaseModel):
    """截止时考核快照（技术方案 13.3）：截止时点回看的既成事实，非当前状态。"""

    result: DeadlineAssessmentResultLiteral
    deadline_at: datetime
    deadline_version_id: OptIdStr
    assignee_user_id: OptIdStr
    evaluated_at: datetime


class InspectionTaskResponse(BaseModel):
    id: IdStr
    task_key: str
    semester_id: IdStr
    inspection_date: date
    week_no: int
    inspection_type: str
    start_period: int
    end_period: int
    course_schedule_id: OptIdStr
    teaching_class_id: OptIdStr
    administrative_class_id: OptIdStr
    course_name_snapshot: str | None
    class_name_snapshot: str | None
    classroom_snapshot: str | None
    require_photo_snapshot: bool
    expected_count_snapshot: int
    expected_count_current: int
    roster_version: int
    status: InspectionTaskStatus
    assignment: TaskAssignmentBrief | None
    lock_version: int
    # Wave 3c：当日适用截止 + 截止时考核快照（未到期或未结算则为 None）。
    deadline_at: datetime | None = None
    deadline_version_id: OptIdStr = None
    deadline_assessment: DeadlineAssessmentBrief | None = None


class TaskRosterMemberResponse(BaseModel):
    student_id: IdStr
    student_no: str
    name: str
    class_name_snapshot: str | None
    grade_year_snapshot: int | None


class TaskRosterResponse(BaseModel):
    task_id: IdStr
    roster_version: int
    items: list[TaskRosterMemberResponse]


# --------------------------------------------------------------------------- #
# 预览 / 生成响应
# --------------------------------------------------------------------------- #
class PlannedTaskBrief(BaseModel):
    """预览样本行：仅关键字段，供前端核对，避免整批明细外泄超大响应体。"""

    task_key: str
    inspection_date: date
    week_no: int
    inspection_type: str
    start_period: int
    end_period: int
    class_name_snapshot: str | None
    course_name_snapshot: str | None
    classroom_snapshot: str | None
    expected_count: int


class GeneratePreviewResponse(BaseModel):
    semester_id: IdStr
    inspection_type: str
    task_count: int  # 计划（去重后）任务总数
    new_task_count: int  # 其中尚不存在、生成时将新建者
    existing_task_count: int  # 命中既有 task_key、将被幂等跳过者
    date_count: int
    student_total: int  # 各计划任务名单人数求和（跨任务可能重叠，仅规模提示）
    within_limit: bool
    max_tasks: int
    sample: list[PlannedTaskBrief]
    sample_truncated: bool


class GenerateResultResponse(BaseModel):
    semester_id: IdStr
    inspection_type: str
    created: int
    existed: int  # 幂等跳过的既有任务数
    total_planned: int
    deadline_days_seeded: int


# --------------------------------------------------------------------------- #
# 排班 / 改派（Wave 3a）
# --------------------------------------------------------------------------- #
class AssignmentSetRequest(BaseModel):
    """人工把某任务分配/改派给指定志愿者。lock_version 乐观锁防并发覆盖。"""

    volunteer_user_id: int = Field(ge=1)
    lock_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=512)


class AutoAssignRequest(BaseModel):
    """自动排班：按学期 + 可选日期/日期范围/显式任务集选范围，可限定候选志愿者。

    范围维度三选一（互斥优先级：task_ids > inspection_date > date_from/date_to）：
    - task_ids：仅对这些未取消任务排班；
    - inspection_date：该查课日的全部未分配任务；
    - date_from/date_to：该区间内全部未分配任务（闭区间）。
    candidate_user_ids 为空表示全体有效志愿者资格池；给出则作为候选子集（仍逐个校验硬约束）。
    """

    semester_id: int = Field(ge=1)
    task_ids: list[int] | None = Field(default=None, max_length=500)
    inspection_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    candidate_user_ids: list[int] | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _check_scope(self) -> AutoAssignRequest:
        has_range = self.date_from is not None and self.date_to is not None
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from 与 date_to 必须同时提供")
        if has_range and self.date_to < self.date_from:  # type: ignore[operator]
            raise ValueError("date_to 不得早于 date_from")
        if not self.task_ids and self.inspection_date is None and not has_range:
            raise ValueError("task_ids / inspection_date / 日期范围 至少提供其一")
        return self


class PlannedAssignment(BaseModel):
    task_id: IdStr
    volunteer_user_id: IdStr


class UnassignedTaskBrief(BaseModel):
    task_id: IdStr
    reason_code: str
    message: str


class AutoAssignResultResponse(BaseModel):
    semester_id: IdStr
    target_task_count: int  # 范围内本次考虑的未分配任务数
    assigned_count: int
    unassigned_count: int
    assigned: list[PlannedAssignment]
    unassigned: list[UnassignedTaskBrief]


# --------------------------------------------------------------------------- #
# 调班申请（Wave 3b）——志愿者对本人当前受派发起，管理人员读取与处理。
# --------------------------------------------------------------------------- #
ChangeRequestStatusLiteral = Literal["PENDING", "APPROVED", "REJECTED"]
ChangeDecisionLiteral = Literal["APPROVED", "REJECTED"]


class ChangeRequestCreateRequest(BaseModel):
    """志愿者对本人当前受派关系（assignment_id）发起调班申请，须写明原因。"""

    assignment_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=512)


class ChangeRequestReviewRequest(BaseModel):
    """管理人员处理申请：通过 / 驳回，可附意见。仅迁移申请状态，不隐式改派。"""

    decision: ChangeDecisionLiteral
    comment: str | None = Field(default=None, max_length=512)


class ChangeRequestResponse(BaseModel):
    id: IdStr
    assignment_id: IdStr
    task_id: IdStr
    request_user_id: IdStr
    reason: str
    status: ChangeRequestStatusLiteral
    processed_by: OptIdStr
    processed_at: datetime | None
    comment: str | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# 取消 / 名单改版 / 截止时间配置 / 截止结算（Wave 3c）
# --------------------------------------------------------------------------- #
class TaskCancelRequest(BaseModel):
    """取消某未取消任务：须写原因，lock_version 乐观锁防并发覆盖。"""

    reason: str = Field(min_length=1, max_length=512)
    lock_version: int = Field(ge=0)


class RosterVersionCreateRequest(BaseModel):
    """执行前更正名单：给出更正后的完整学生集合，生成新版本并冻结成员快照。"""

    student_ids: list[int] = Field(default_factory=list, max_length=2000)
    reason: str = Field(min_length=1, max_length=512)
    lock_version: int = Field(ge=0)


class RosterVersionResponse(BaseModel):
    version_no: int
    reason: str | None
    created_by: OptIdStr
    member_count: int
    created_at: datetime


class SubmissionDeadlineDefaultResponse(BaseModel):
    """全局默认提交截止时刻（配置管理，改它属部署/配置动作，非运行时写接口）。"""

    time: str  # 本地墙上时钟 HH:MM
    utc_offset_hours: float
    description: str


class SubmissionDeadlineDayResponse(BaseModel):
    semester_id: IdStr
    inspection_date: date
    deadline_at: datetime  # naive-UTC
    version: int
    updated_by: OptIdStr
    reason: str | None
    task_count: int = 0  # 当日未取消任务数，供后台显示"影响任务数"


class SubmissionDeadlineVersionResponse(BaseModel):
    version_no: int
    deadline_at: datetime
    changed_by: OptIdStr
    reason: str | None
    created_at: datetime


class DeadlineDayUpdateRequest(BaseModel):
    """改指定查课日截止时间：给本地 HH:MM，须写原因，day_version 乐观锁（自 1 起）。"""

    time: str = Field(min_length=5, max_length=5)  # HH:MM
    reason: str = Field(min_length=1, max_length=512)
    lock_version: int = Field(ge=1)


class DeadlineSettleRequest(BaseModel):
    """有界同步结算到期任务的截止时考核快照（不依赖页面访问，技术方案 13.3）。

    范围：semester_id 必填；可再按 inspection_date 缩小到某日，或用 task_ids 指定集合。
    limit 为单批处理上限，超出部分留待下次结算。
    """

    semester_id: int = Field(ge=1)
    inspection_date: date | None = None
    task_ids: list[int] | None = Field(default=None, max_length=500)
    limit: int = Field(default=500, ge=1, le=2000)


class SettledTaskBrief(BaseModel):
    task_id: IdStr
    result: DeadlineAssessmentResultLiteral


class DeadlineSettleResultResponse(BaseModel):
    semester_id: IdStr
    considered: int  # 本次纳入结算判定的到期候选任务数（受 limit 约束）
    settled: int  # 本次新建考核快照数
    already_settled: int  # 已有快照、幂等跳过数
    not_due: int  # 尚未到期、不生成快照数
    results: list[SettledTaskBrief]


# --------------------------------------------------------------------------- #
# 排班冲突原因码（Wave 3a 硬约束）——集中定义，服务与测试共用字面量。
# --------------------------------------------------------------------------- #
REASON_NOT_VOLUNTEER = "NOT_VOLUNTEER"  # 账号停用或非志愿者身份
REASON_NO_QUALIFICATION = "NO_QUALIFICATION"  # 本学期无有效志愿者资格（含未绑定学生）
REASON_SELF_CLASS = "SELF_CLASS_AVOID"  # 被查名单含本人行政班学生，本班回避
REASON_TASK_CONFLICT = "TASK_TIME_CONFLICT"  # 与本人其他查课任务时段重叠
REASON_OWN_CLASS = "OWN_CLASS_CONFLICT"  # 与本人课表时段冲突
REASON_DAY_CAP = "DAY_TASK_CAP"  # 超出单日受派上限（可配置软约束）
REASON_TASK_CANCELED = "TASK_CANCELED"  # 目标任务已取消
REASON_DEADLINE_EARLY = "DEADLINE_BEFORE_TASK_END"  # 截止时间早于当日最晚任务结束时刻


__all__ = [
    "InspectionGenerateRequest",
    "InspectionTaskResponse",
    "TaskAssignmentBrief",
    "TaskRosterMemberResponse",
    "TaskRosterResponse",
    "PlannedTaskBrief",
    "GeneratePreviewResponse",
    "GenerateResultResponse",
    "InspectionTypeLiteral",
    "InspectionTaskStatus",
    "AssignmentSetRequest",
    "AutoAssignRequest",
    "AutoAssignResultResponse",
    "PlannedAssignment",
    "UnassignedTaskBrief",
    "ChangeRequestCreateRequest",
    "ChangeRequestReviewRequest",
    "ChangeRequestResponse",
    "ChangeRequestStatusLiteral",
    "ChangeDecisionLiteral",
    "DeadlineAssessmentBrief",
    "DeadlineAssessmentResultLiteral",
    "TaskCancelRequest",
    "RosterVersionCreateRequest",
    "RosterVersionResponse",
    "SubmissionDeadlineDefaultResponse",
    "SubmissionDeadlineDayResponse",
    "SubmissionDeadlineVersionResponse",
    "DeadlineDayUpdateRequest",
    "DeadlineSettleRequest",
    "SettledTaskBrief",
    "DeadlineSettleResultResponse",
]
