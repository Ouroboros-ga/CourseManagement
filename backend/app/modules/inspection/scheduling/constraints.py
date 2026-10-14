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


def group_quota_rejection(task: Task, occupied: Sequence[Task]) -> str | None:
    if task.group_id is None:
        return None
    week = task.day.isocalendar()[:2]
    relevant = [other for other in occupied if other.id != task.id
                and other.day.isocalendar()[:2] == week
                and (task.count_all_groups or other.group_id == task.group_id)]
    if task.group_daily_limit is not None and sum(other.day == task.day for other in relevant) >= task.group_daily_limit:
        return "DAY_CAP_EXCEEDED"
    if task.group_weekly_limit is not None and len(relevant) >= task.group_weekly_limit:
        return "WEEK_CAP_EXCEEDED"
    return None


def group_plan_rejection(task: Task, occupied: Sequence[Task]) -> str | None:
    """新增受派同时遵守其自身和同周既有受派冻结的跨组配额。"""
    hypothetical = [other for other in occupied if other.id != task.id] + [task]
    for other in hypothetical:
        if (other.day.isocalendar()[:2] == task.day.isocalendar()[:2]
                and (other.id == task.id or other.count_all_groups
                     or other.group_id == task.group_id)):
            reason = group_quota_rejection(other, hypothetical)
            if reason:
                return reason
    return None
