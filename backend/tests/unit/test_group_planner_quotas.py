from datetime import date, timedelta

from app.modules.inspection.scheduling.loader import Snapshot
from app.modules.inspection.scheduling.models import Task, Volunteer
from app.modules.inspection.scheduling.planner import plan_assignments
from app.modules.inspection.scheduling.validation import validate_plan


def grouped(tid, day, group, *, count_all=True, daily=5, weekly=1):
    return Task(
        tid,
        day,
        tid * 10,
        tid * 10 + 5,
        frozenset({1, 2}),
        group_id=group,
        group_daily_limit=daily,
        group_weekly_limit=weekly,
        count_all_groups=count_all,
    )


def test_weekly_group_quota_participates_in_planning_and_locked_validation():
    monday = date(2026, 10, 12)
    tasks = [grouped(1, monday, 10), grouped(2, monday + timedelta(days=1), 10)]
    people = [Volunteer(1), Volunteer(2)]
    result = plan_assignments(tasks, people)
    assert len(result.assignments) == 2
    assert set(result.assignments.values()) == {1, 2}
    assert validate_plan(Snapshot(tasks, people, {}), {1: 1, 2: 1}) == (1, "WEEK_CAP_EXCEEDED")


def test_all_group_cap_counts_other_groups_but_group_cap_does_not():
    day = date(2026, 10, 12)
    existing = Task(90, day, 0, 5, frozenset(), group_id=20)
    person = Volunteer(1, existing=(existing,))
    blocked = grouped(1, day, 10)
    result = plan_assignments([blocked], [person])
    assert result.unassigned == {1: "WEEK_CAP_EXCEEDED"}
    allowed = grouped(2, day, 10, count_all=False)
    assert plan_assignments([allowed], [person]).assignments == {2: 1}


def test_later_permissive_group_cannot_overflow_another_planned_all_group_cap():
    day = date(2026, 10, 12)
    strict = grouped(1, day, 10)
    permissive = grouped(2, day + timedelta(days=1), 20, count_all=False, weekly=20)
    result = plan_assignments([strict, permissive], [Volunteer(1)])
    assert len(result.assignments) == 1


def test_existing_strict_group_cap_survives_later_permissive_group():
    day = date(2026, 10, 12)
    existing = grouped(90, day, 10)
    incoming = grouped(2, day + timedelta(days=1), 20, count_all=False, weekly=20)
    people = [Volunteer(1, existing=(existing,))]
    result = plan_assignments([incoming], people)
    assert result.assignments == {}
    assert result.unassigned == {2: "WEEK_CAP_EXCEEDED"}
    assert validate_plan(Snapshot([incoming], people, {}), {2: 1}) == (2, "WEEK_CAP_EXCEEDED")
