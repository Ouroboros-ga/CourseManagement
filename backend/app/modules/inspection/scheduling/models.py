"""排班输入是本轮快照，planner 不修改输入或数据库已有受派。"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Task:
    id: int
    day: date
    start: int
    end: int
    candidates: frozenset[int]
    # start/end 必须在同一坐标系内，半开区间。适配旧模型用 [首节,末节+1)。
    parts: frozenset[str] = frozenset()
    cluster: str | None = None
    minutes: tuple[int, int] | None = None


@dataclass(frozen=True)
class Volunteer:
    id: int
    semester_load: int = 0
    existing: tuple[Task, ...] = ()


@dataclass
class Plan:
    assignments: dict[int, int] = field(default_factory=dict)
    unassigned: dict[int, str] = field(default_factory=dict)
    repair_attempts: int = 0
