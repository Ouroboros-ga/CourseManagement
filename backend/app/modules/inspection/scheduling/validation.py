"""锁内复核原计划，不重新优化；任何失效都由调用方整批回滚。"""

from collections import defaultdict
from datetime import date

from .constraints import rejection
from .loader import Snapshot
from .models import Task


def validate_plan(
    snapshot: Snapshot, assignments: dict[int, int], *, day_cap: int = 0, week_cap: int = 0,
) -> tuple[int, str] | None:
    tasks = {task.id: task for task in snapshot.tasks}
    today: dict[tuple[int, date], list[Task]] = defaultdict(list)
    weekly: dict[tuple[int, int, int], int] = defaultdict(int)
    for volunteer in snapshot.volunteers:
        for existing in volunteer.existing:
            today[volunteer.id, existing.day].append(existing)
            year, week, _ = existing.day.isocalendar()
            weekly[volunteer.id, year, week] += 1
    for tid, vid in sorted(assignments.items()):
        task = tasks.get(tid)
        if task is None or vid not in task.candidates:
            return tid, snapshot.static_failures.get(tid, "NO_QUALIFICATION")
        year, week, _ = task.day.isocalendar()
        reason = rejection(task, today[vid, task.day], day_cap, week_cap, weekly[vid, year, week])
        if reason:
            return tid, reason
        today[vid, task.day].append(task)
        weekly[vid, year, week] += 1
    return None
