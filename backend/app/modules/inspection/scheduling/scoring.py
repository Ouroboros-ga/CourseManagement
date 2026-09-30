"""软成本只影响选择顺序；缺少时间/地点不能变成硬拒绝条件。"""

from collections.abc import Sequence

from .models import Task


def time_delta(task: Task, occupied: Sequence[Task]) -> int:
    today = [other for other in occupied if other.day == task.day]
    parts = set().union(*(other.parts for other in today))
    unknown = sum(not other.parts for other in today)
    before = len(parts) + unknown
    after = len(parts | task.parts) + unknown + (not task.parts)
    return after + max(0, after - 1) - before - max(0, before - 1)


def _transition(left: Task | None, right: Task | None) -> int:
    if left is None or right is None:
        return 0
    if not left.cluster or not right.cluster:
        return 1
    if left.cluster == right.cluster:
        return 0
    if left.minutes and right.minutes and 0 <= right.minutes[0] - left.minutes[1] <= 30:
        return 2
    return 1


def location_delta(task: Task, occupied: Sequence[Task]) -> int:
    today = sorted((other for other in occupied if other.day == task.day),
                   key=lambda other: (other.start, other.id))
    before = next((other for other in reversed(today) if other.end <= task.start), None)
    after = next((other for other in today if other.start >= task.end), None)
    return (_transition(before, task) + _transition(task, after)
            - _transition(before, after))
