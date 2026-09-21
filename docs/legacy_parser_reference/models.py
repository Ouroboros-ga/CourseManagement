"""领域对象合同（M1a）。

本文件只定义纯数据结构，不依赖 Excel / SQLite / Streamlit。
字段合同见 docs/superpowers/plans/2026-09-17-course-scheduler.md 第 4.4 节。

约定：
- 所有 ID 均为 str，避免学号前导零丢失。
- Slot = (week, weekday, slot)，依次为周次、星期（1=周一..7=周日）、标准大节（1..5）。
- 默认大节映射见 normalize.DEFAULT_SLOT_MAPPING；若配置变化必须记录在方案规则快照中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# (周次, 星期 1-7, 标准大节 1-5)
Slot = tuple[int, int, int]

ALGORITHM_VERSION = "greedy-v1"


class OverrideAction(str, Enum):
    """个人修正动作。"""

    ADD = "ADD"
    CANCEL_COURSE = "CANCEL_COURSE"


class AssignmentSource(str, Enum):
    """安排来源。"""

    AUTO = "auto"
    MANUAL = "manual"
    RETAINED = "retained"


class PlanStatus(str, Enum):
    """方案状态。"""

    DRAFT = "DRAFT"
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class Volunteer:
    """志愿者。id 通常等于 student_no（文本，保留前导零）。"""

    id: str
    student_no: str
    name: str
    class_id: str


@dataclass(frozen=True)
class CourseEntry:
    """展开后的一条课程占用。

    id 为原始 course_id（同一课程多周/多格会有多条记录共享同一 id）。
    """

    id: str
    class_id: str
    slot: Slot
    course_name: str
    location: str = ""


@dataclass(frozen=True)
class PersonalOverride:
    """个人修正展开后的一条记录。

    - ADD：course_id 为 None，slot 为独立占用格。
    - CANCEL_COURSE：course_id 必填，slot 为取消的具体时间格。
    """

    id: str
    volunteer_id: str
    action: OverrideAction
    course_id: str | None
    slot: Slot


@dataclass(frozen=True)
class Task:
    """展开后的查课任务，每个 Task 只占一个标准大节。

    id 由原始 task_id 与具体时间格组成，形如 ``T001@w03d3p2``，保证同一输入下稳定。
    """

    id: str
    target_class_id: str
    slot: Slot
    location: str
    required_people: int
    raw_id: str = ""


@dataclass(frozen=True)
class Assignment:
    task_id: str
    volunteer_id: str
    locked: bool = False
    source: AssignmentSource = AssignmentSource.AUTO


@dataclass(frozen=True)
class Rules:
    forbid_own_class: bool = True
    slot_mapping: dict[int, int] = field(default_factory=dict)
    algorithm_version: str = ALGORITHM_VERSION

    def __post_init__(self) -> None:
        # 避免可变默认值共享：空 dict 表示使用默认映射，调用方通过 normalize 解析。
        pass


@dataclass(frozen=True)
class Issue:
    """结构化问题，不适用的定位字段为 None。"""

    code: str
    message: str
    sheet: str | None = None
    row: int | None = None
    field: str | None = None
    task_id: str | None = None
    volunteer_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    blocking_errors: tuple[Issue, ...] = ()
    warnings: tuple[Issue, ...] = ()

    @property
    def ok(self) -> bool:
        return len(self.blocking_errors) == 0


@dataclass(frozen=True)
class Shortage:
    """任务缺口。reason_code 描述当前筛选结果，不声称无解。"""

    task_id: str
    required: int
    assigned: int
    missing: int
    reason_code: str


@dataclass(frozen=True)
class ScheduleResult:
    assignments: tuple[Assignment, ...] = ()
    shortages: tuple[Shortage, ...] = ()
    validation: ValidationResult = ValidationResult()


@dataclass(frozen=True)
class InputSnapshot:
    term_id: str
    total_weeks: int
    volunteers: tuple[Volunteer, ...] = ()
    courses: tuple[CourseEntry, ...] = ()
    overrides: tuple[PersonalOverride, ...] = ()
    tasks: tuple[Task, ...] = ()


def make_task_id(raw_id: str, slot: Slot) -> str:
    """由原始 task_id 与时间格生成稳定的展开任务标识。"""
    week, weekday, period = slot
    return f"{raw_id}@w{week:02d}d{weekday}p{period}"


def make_course_key(course_id: str, slot: Slot) -> str:
    """课程展开记录的调试键（不作为主键）。"""
    week, weekday, period = slot
    return f"{course_id}@w{week:02d}d{weekday}p{period}"
