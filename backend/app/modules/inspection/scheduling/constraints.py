"""动态硬约束。资格、本人课程、本班回避由加载器形成静态候选集合。"""

from collections.abc import Sequence

from .models import Task


def rejection(
    task: Task, today: Sequence[Task], day_cap: int,
    week_cap: int = 0, week_count: int = 0,
) -> str | None:
    if any(task.start < other.end and other.start < task.end for other in today):
        return "TASK_TIME_CONFLICT"
    if day_cap > 0 and len(today) >= day_cap:
        return "DAY_CAP_EXCEEDED"
    if week_cap > 0 and week_count >= week_cap:
        return "WEEK_CAP_EXCEEDED"
    return None
