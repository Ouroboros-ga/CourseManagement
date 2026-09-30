"""动态稀缺优先 + 公平容差 + 一层换位；不保证全局最优。

每次修复最多搬动一个本轮任务，且必须净增一个分配；固定受派不可移动。
修复预算按试探次数计数，避免时间预算使相同输入产生不稳定结果。
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from .constraints import rejection
from .models import Plan, Task, Volunteer
from .scoring import location_delta, time_delta


def plan_assignments(
    tasks: Sequence[Task], volunteers: Sequence[Volunteer], *,
    day_cap: int = 0, week_cap: int = 0, repair_budget: int = 1000,
) -> Plan:
    if day_cap < 0 or week_cap < 0 or repair_budget < 0:
        raise ValueError("排班上限和修复预算不能为负")
    by_id = {task.id: task for task in tasks}
    people = {vol.id: vol for vol in volunteers}
    if len(by_id) != len(tasks) or len(people) != len(volunteers):
        raise ValueError("任务或志愿者 ID 重复")
    if any(task.start >= task.end for task in tasks):
        raise ValueError("任务起止区间无效")

    def week(day: date) -> tuple[int, int]:
        iso = day.isocalendar()
        return iso.year, iso.week

    occupied: dict[int, dict[date, list[Task]]] = {}
    weekly: dict[int, dict[tuple[int, int], int]] = {}
    for vid, vol in people.items():
        days: dict[date, list[Task]] = defaultdict(list)
        weeks: dict[tuple[int, int], int] = defaultdict(int)
        for existing in vol.existing:
            days[existing.day].append(existing)
            weeks[week(existing.day)] += 1
        occupied[vid] = days
        weekly[vid] = weeks
    loads = {vid: vol.semester_load for vid, vol in people.items()}
    plan = Plan()

    def legal(task: Task, vid: int) -> bool:
        return (vid in people and rejection(task, occupied[vid].get(task.day, ()), day_cap,
                                            week_cap, weekly[vid].get(week(task.day), 0)) is None)

    def score(task: Task, vid: int) -> tuple[int, int, int, int, int]:
        today = occupied[vid].get(task.day, ())
        return (time_delta(task, today), location_delta(task, today),
                len(today), loads[vid], vid)

    def put(task: Task, vid: int) -> None:
        plan.assignments[task.id] = vid
        occupied[vid].setdefault(task.day, []).append(task)
        key = week(task.day)
        weekly[vid][key] = weekly[vid].get(key, 0) + 1
        loads[vid] += 1

    def remove(task: Task, vid: int) -> None:
        del plan.assignments[task.id]
        occupied[vid][task.day].remove(task)
        key = week(task.day)
        weekly[vid][key] -= 1
        loads[vid] -= 1

    pending = list(tasks)
    options = {task.id: {v for v in task.candidates & people.keys() if legal(task, v)}
               for task in pending}
    while pending:
        task = min(pending, key=lambda t: (len(options[t.id]), t.day, t.start, t.id))
        pending.remove(task)
        candidates = options[task.id]
        if candidates:
            minimum = min(loads[v] for v in candidates)
            fair = [v for v in candidates if loads[v] <= minimum + 1]
            chosen = min(fair, key=lambda v: score(task, v))
            put(task, chosen)
            # 当天占用和同周上限可能使该人的候选关系失效。
            for other in pending:
                if ((other.day == task.day or (week_cap and week(other.day) == week(task.day)))
                        and chosen in options[other.id]
                        and not legal(other, chosen)):
                    options[other.id].discard(chosen)

    # 仅遍历最终未分配任务一轮，不反复回溯搜索。先直接重试，再尝试一层搬移。
    for task in sorted(tasks, key=lambda t: (t.day, t.start, t.id)):
        if task.id in plan.assignments:
            continue
        fixed_candidates = sorted(task.candidates & people.keys())
        direct = [v for v in fixed_candidates if legal(task, v)]
        if direct:
            minimum = min(loads[v] for v in direct)
            put(task, min((v for v in direct if loads[v] <= minimum + 1),
                          key=lambda v: score(task, v)))
            continue
        repaired = False
        for vid in sorted(fixed_candidates, key=lambda v: (loads[v], v)):
            movable = sorted((by_id[tid] for tid, owner in plan.assignments.items()
                              if owner == vid and (by_id[tid].day == task.day or
                                                   (week_cap and week(by_id[tid].day) ==
                                                    week(task.day)))),
                             key=lambda t: (t.day, t.start, t.id))
            for other in movable:
                if plan.repair_attempts >= repair_budget:
                    break
                plan.repair_attempts += 1
                remove(other, vid)
                if not legal(task, vid):
                    put(other, vid)
                    continue
                # 暂时放入 T，检查搬移后的完整计划，防止日上限或其他占用遗漏。
                put(task, vid)
                alternatives = []
                for target in sorted(other.candidates & people.keys()):
                    if plan.repair_attempts >= repair_budget:
                        break
                    plan.repair_attempts += 1
                    if target != vid and legal(other, target):
                        alternatives.append(target)
                if alternatives:
                    # 增加完成率时允许离开公平域，但优先较低负载的替代人。
                    chosen = min(alternatives, key=lambda v: (loads[v], score(other, v)))
                    put(other, chosen)
                    repaired = True
                    break
                remove(task, vid)
                put(other, vid)
            if repaired or plan.repair_attempts >= repair_budget:
                break

    for task in tasks:
        if task.id not in plan.assignments:
            reasons = [rejection(task, occupied[v].get(task.day, ()), day_cap,
                                 week_cap, weekly[v].get(week(task.day), 0))
                       for v in sorted(task.candidates & people.keys())]
            plan.unassigned[task.id] = next((r for r in reasons if r), "NO_QUALIFICATION")
    # 输出顺序稳定；修复失败可能改变内部 dict 插入顺序，不能泄露到接口。
    plan.assignments = dict(sorted(plan.assignments.items()))
    plan.unassigned = dict(sorted(plan.unassigned.items()))
    return plan
