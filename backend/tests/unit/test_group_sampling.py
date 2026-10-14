import pytest
from app.core.exceptions import ConflictError


def test_sampling_never_fills_shortage_from_other_types_or_classes():
    from app.modules.inspection.group_sampling import choose_exact

    candidates = [("a", frozenset({1})), ("b", frozenset({2}))]
    with pytest.raises(ConflictError):
        choose_exact(candidates, {1: 2}, "fixed-seed")


def test_combined_class_occurrences_count_once_for_each_class():
    from app.modules.inspection.group_sampling import choose_exact

    candidates = [("both", frozenset({1, 2})), ("a", frozenset({1})), ("b", frozenset({2}))]
    selected = choose_exact(candidates, {1: 1, 2: 1}, "fixed-seed")
    by_key = dict(candidates)
    assert sum(1 for k in selected if 1 in by_key[k]) == 1
    assert sum(1 for k in selected if 2 in by_key[k]) == 1
    assert selected == choose_exact(candidates, {1: 1, 2: 1}, "fixed-seed")


def test_sample_does_not_include_unrequested_class_in_joint_target():
    from app.modules.inspection.group_sampling import choose_exact

    candidates = [("joint", frozenset({1, 2})), ("own", frozenset({1}))]
    assert choose_exact(candidates, {1: 1}, "fixed-seed") == ["own"]
