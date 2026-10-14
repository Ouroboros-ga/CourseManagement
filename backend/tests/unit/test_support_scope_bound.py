from types import SimpleNamespace

import pytest
from app.modules.volunteer.eligibility_index import EligibilityIndex

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_candidates import (
    test_authorized_foreign_support_appears_only_while_effective as exercise_support,
)


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_support_scope_does_not_expand_with_group_configuration(campus, monkeypatch):
    # Exercise the real grant and candidate path before inspecting the immutable cap.
    exercise_support(campus, monkeypatch)
    from app.modules.volunteer.member_models import VolunteerGroupSupport
    from sqlalchemy import select

    db = campus[1]
    support = db.scalar(select(VolunteerGroupSupport))
    assert support.scope_snapshot["course_type_ids"]
    allowed = support.scope_snapshot["course_type_ids"][0]
    task = SimpleNamespace(
        course_type_id_snapshot=int(allowed), id=None, administrative_class_id=None
    )
    assert EligibilityIndex.support_covers_scope(support, task, set())
    task.course_type_id_snapshot = int(allowed) + 100000
    assert not EligibilityIndex.support_covers_scope(support, task, set())
    support.scope_snapshot = {
        "course_type_ids": [allowed],
        "class_mode": "SPECIFIC",
        "class_ids": ["10"],
    }
    task.course_type_id_snapshot = int(allowed)
    assert EligibilityIndex.support_covers_scope(support, task, {10})
    assert not EligibilityIndex.support_covers_scope(support, task, {10, 11})
    assert not EligibilityIndex.support_covers_scope(support, task, set())
    support.scope_snapshot = None
    assert not EligibilityIndex.support_covers_scope(support, task, {10})
