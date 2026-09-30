"""手工构造候选图验证排班行为，不依赖数据库或生产候选计算。"""

from datetime import date, timedelta

from app.modules.inspection.scheduling.models import Task, Volunteer
from app.modules.inspection.scheduling.planner import plan_assignments
from app.modules.inspection.scheduling.scoring import location_delta, time_delta

DAY = date(2026, 9, 22)


def task(i, candidates, start=0, end=1, **kw):
    return Task(i, DAY, start, end, frozenset(candidates), **kw)


def test_scarce_task_gets_only_candidate_before_flexible_task():
    result = plan_assignments([task(1, [1, 2]), task(2, [1])],
                              [Volunteer(1), Volunteer(2)])
    assert result.assignments == {2: 1, 1: 2}


def test_load_includes_current_batch_and_preexisting_semester_work():
    tasks = [task(i, [1, 2], i, i + 1) for i in range(1, 5)]
    result = plan_assignments(tasks, [Volunteer(1, semester_load=10), Volunteer(2)])
    assert set(result.assignments.values()) == {2}
    balanced = plan_assignments(tasks, [Volunteer(1), Volunteer(2)])
    assert list(balanced.assignments.values()).count(1) == 2
    assert list(balanced.assignments.values()).count(2) == 2


def test_repair_moves_one_provisional_task_to_increase_coverage():
    tasks = [task(1, [1, 2]), task(2, [1, 3]), task(3, [1, 3])]
    volunteers = [Volunteer(1), Volunteer(2), Volunteer(3)]
    assert len(plan_assignments(tasks, volunteers, repair_budget=0).assignments) == 2
    result = plan_assignments(tasks, volunteers)
    assert result.assignments == {1: 2, 2: 3, 3: 1}
    assert not result.unassigned
    # 输入不被试探性修复修改；重复运行必须稳定。
    assert result == plan_assignments(list(reversed(tasks)), list(reversed(volunteers)))


def test_repair_can_leave_fairness_band_but_never_move_fixed_assignment():
    tasks = [task(1, [1, 2]), task(2, [1, 3]), task(3, [1, 3])]
    result = plan_assignments(tasks, [Volunteer(1), Volunteer(2, semester_load=20),
                                      Volunteer(3)])
    assert len(result.assignments) == 3
    fixed = task(99, [])
    result = plan_assignments([task(1, [1])], [Volunteer(1, existing=(fixed,),
                                                               semester_load=1)])
    assert not result.assignments
    assert result.unassigned[1] == "TASK_TIME_CONFLICT"


def test_day_cap_and_half_open_boundaries():
    tasks = [task(1, [1], 0, 1), task(2, [1], 1, 2), task(3, [1], 2, 3)]
    result = plan_assignments(tasks, [Volunteer(1)], day_cap=2)
    assert result.assignments == {1: 1, 2: 1}
    assert result.unassigned == {3: "DAY_CAP_EXCEEDED"}


def test_time_cost_distinguishes_same_empty_and_other_part():
    morning = task(1, [1], parts=frozenset({"MORNING"}))
    afternoon = task(2, [], parts=frozenset({"AFTERNOON"}))
    assert time_delta(morning, [morning]) == 0
    assert time_delta(morning, []) == 1
    assert time_delta(morning, [afternoon]) == 2
    spanning = task(3, [], parts=frozenset({"MORNING", "AFTERNOON"}))
    assert time_delta(spanning, []) == 3


def test_same_morning_preferred_within_fairness_band():
    fixed = task(99, [], 0, 1, parts=frozenset({"MORNING"}))
    new = task(1, [1, 2], 1, 2, parts=frozenset({"MORNING"}))
    result = plan_assignments([new], [Volunteer(1), Volunteer(2, 1, (fixed,))])
    assert result.assignments == {1: 2}


def test_location_insertion_subtracts_replaced_edge():
    before = task(1, [], 0, 1, cluster="A", minutes=(480, 500))
    after = task(3, [], 4, 5, cluster="B", minutes=(550, 570))
    new = task(2, [], 2, 3, cluster="A", minutes=(520, 530))
    # 原 A→B 间隔 50 分钟成本 1；新增 0 + 2，增量为 1。
    assert location_delta(new, [before, after]) == 1
    assert location_delta(task(4, []), []) == 0


def test_failed_repair_restores_load_and_occupancy():
    tasks = [task(1, [1]), task(2, [1]), task(3, [1], 1, 2)]
    result = plan_assignments(tasks, [Volunteer(1)], day_cap=2)
    assert result.assignments == {1: 1, 3: 1}
    assert set(result.unassigned) == {2}


def test_empty_candidates_and_repair_budget():
    assert plan_assignments([task(1, [])], []).unassigned == {1: "NO_QUALIFICATION"}
    tasks = [task(1, [1, 2]), task(2, [1, 3]), task(3, [1, 3])]
    result = plan_assignments(tasks, [Volunteer(1), Volunteer(2), Volunteer(3)],
                              repair_budget=1)
    assert result.repair_attempts <= 1
    baseline = plan_assignments(tasks, [Volunteer(1), Volunteer(2), Volunteer(3)],
                                repair_budget=0)
    assert result.assignments == baseline.assignments
    assert result.unassigned == baseline.unassigned


def test_small_cases_against_independent_exhaustive_oracle():
    from itertools import product
    from random import Random

    rng = Random(20260923)
    for _ in range(40):
        tasks = [task(i, [v for v in (1, 2, 3) if rng.random() < 0.65],
                      start=i % 3, end=i % 3 + 2) for i in range(5)]
        people = [Volunteer(i) for i in (1, 2, 3)]

        def valid(owners, tasks=tasks):
            for vid in (1, 2, 3):
                assigned = [t for t, owner in zip(tasks, owners, strict=True) if owner == vid]
                if len(assigned) > 2:
                    return False
                for i, left in enumerate(assigned):
                    for right in assigned[i + 1:]:
                        if max(left.start, right.start) < min(left.end, right.end):
                            return False
            return True

        optimum = max(sum(v is not None for v in owners)
                      for owners in product(*[(None, *sorted(t.candidates)) for t in tasks])
                      if valid(owners))
        baseline = plan_assignments(tasks, people, day_cap=2, repair_budget=0)
        result = plan_assignments(tasks, people, day_cap=2)
        assert len(baseline.assignments) <= len(result.assignments) <= optimum
        assert valid([result.assignments.get(t.id) for t in tasks])
        assert all(owner in tasks[tid].candidates for tid, owner in result.assignments.items())


def test_only_affected_candidates_are_rechecked(monkeypatch):
    from app.modules.inspection.scheduling import planner

    original = planner.rejection
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(planner, "rejection", counted)
    tasks = [task(i, range(20), i, i + 1) for i in range(40)]
    result = planner.plan_assignments(tasks, [Volunteer(v) for v in range(20)])
    assert len(result.assignments) == 40
    # 初始化每个组合一次；每次选人只重新检查该人的剩余候选关系。
    assert calls <= 40 * 20 + 40 * 39 // 2


def test_unknown_parts_keep_known_fragment_cost_and_have_positive_own_cost():
    morning = task(1, [], parts=frozenset({"MORNING"}))
    unknown = task(2, [])
    afternoon = task(3, [], parts=frozenset({"AFTERNOON"}))
    assert time_delta(afternoon, [morning, unknown]) == 2
    assert time_delta(unknown, [morning]) > 0


def test_scoring_ignores_occupancy_on_other_dates():
    yesterday = Task(99, DAY - timedelta(days=1), 0, 1, frozenset(),
                     parts=frozenset({"MORNING"}), cluster="A")
    today = task(1, [], 2, 3, parts=frozenset({"AFTERNOON"}), cluster="B")
    assert time_delta(today, [yesterday]) == 1
    assert location_delta(today, [yesterday]) == 0


def test_week_cap_counts_existing_but_not_semester_load_across_iso_year():
    monday = date(2026, 12, 28)
    sunday = date(2027, 1, 3)
    next_monday = date(2027, 1, 4)
    existing = Task(99, monday, 0, 1, frozenset())
    tasks = [Task(1, sunday, 1, 2, frozenset({1})),
             Task(2, next_monday, 1, 2, frozenset({1}))]
    result = plan_assignments(tasks, [Volunteer(1, semester_load=50, existing=(existing,))],
                              week_cap=1)
    assert result.assignments == {2: 1}
    assert result.unassigned == {1: "WEEK_CAP_EXCEEDED"}


def test_week_cap_rechecks_later_dates_in_the_same_week():
    monday = date(2026, 9, 21)
    tasks = [Task(1, monday, 0, 1, frozenset({1})),
             Task(2, monday + timedelta(days=1), 0, 1, frozenset({1, 2})),
             Task(3, monday + timedelta(days=2), 0, 1, frozenset({2}))]
    result = plan_assignments(tasks, [Volunteer(1), Volunteer(2)], week_cap=1,
                              repair_budget=0)
    assert result.assignments == {1: 1, 2: 2}
    assert result.unassigned == {3: "WEEK_CAP_EXCEEDED"}


def test_week_repair_moves_another_date_and_budget_rollback_is_exact():
    monday = date(2026, 9, 21)
    tasks = [Task(1, monday, 0, 1, frozenset({1, 2})),
             Task(2, monday + timedelta(days=1), 0, 1, frozenset({1, 3})),
             Task(3, monday + timedelta(days=2), 0, 1, frozenset({1, 3}))]
    people = [Volunteer(1), Volunteer(2), Volunteer(3)]
    baseline = plan_assignments(tasks, people, week_cap=1, repair_budget=0)
    limited = plan_assignments(tasks, people, week_cap=1, repair_budget=1)
    repaired = plan_assignments(tasks, people, week_cap=1)
    assert limited.assignments == baseline.assignments
    assert limited.unassigned == baseline.unassigned
    assert repaired.assignments == {1: 2, 2: 3, 3: 1}
    assert repaired == plan_assignments(list(reversed(tasks)), list(reversed(people)),
                                        week_cap=1)


def test_week_cap_zero_is_unlimited_and_negative_is_invalid():
    from pytest import raises

    monday = date(2026, 9, 21)
    tasks = [Task(i, monday + timedelta(days=i), 0, 1, frozenset({1})) for i in range(2)]
    assert len(plan_assignments(tasks, [Volunteer(1)], week_cap=0).assignments) == 2
    with raises(ValueError):
        plan_assignments(tasks, [Volunteer(1)], week_cap=-1)


def test_unassigned_reports_first_candidate_rejection_not_an_aggregate():
    monday = date(2026, 9, 21)
    blocked_by_week = Task(91, monday + timedelta(days=1), 4, 5, frozenset())
    blocked_by_time = Task(92, monday, 1, 3, frozenset())
    pending = Task(1, monday, 2, 4, frozenset({1, 2}))
    result = plan_assignments(
        [pending],
        [Volunteer(1, existing=(blocked_by_week,)), Volunteer(2, existing=(blocked_by_time,))],
        week_cap=1,
    )
    assert result.assignments == {}
    assert result.unassigned == {1: "WEEK_CAP_EXCEEDED"}


def test_unassigned_prefers_time_conflict_over_week_cap_for_one_candidate():
    monday = date(2026, 9, 21)
    occupied = Task(91, monday, 1, 3, frozenset())
    pending = Task(1, monday, 2, 4, frozenset({1}))
    result = plan_assignments([pending], [Volunteer(1, existing=(occupied,))], week_cap=1)
    assert result.unassigned == {1: "TASK_TIME_CONFLICT"}
