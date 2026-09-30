from datetime import date

from app.modules.inspection.scheduling.loader import Snapshot
from app.modules.inspection.scheduling.models import Task, Volunteer
from app.modules.inspection.scheduling.validation import validate_plan


def test_final_validation_rejects_changed_candidate_without_replanning():
    task = Task(1, date(2026, 9, 28), 1, 3, frozenset({2}))
    snapshot = Snapshot([task], [Volunteer(1), Volunteer(2)], {})
    assert validate_plan(snapshot, {1: 1}) == (1, "NO_QUALIFICATION")


def test_final_validation_counts_fixed_and_all_batch_dates_in_week():
    monday = Task(1, date(2026, 9, 28), 1, 3, frozenset({1}))
    tuesday = Task(2, date(2026, 9, 29), 1, 3, frozenset({1}))
    existing = Task(3, date(2026, 10, 2), 1, 3, frozenset())
    snapshot = Snapshot([monday, tuesday], [Volunteer(1, 3, (existing,))], {})
    assert validate_plan(snapshot, {1: 1, 2: 1}, week_cap=2) == (2, "WEEK_CAP_EXCEEDED")
    assert validate_plan(snapshot, {1: 1, 2: 1}, week_cap=3) is None
