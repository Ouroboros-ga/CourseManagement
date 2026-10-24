"""旧支援范围仅保留历史，不再参与任何候选或排班判定。"""

from datetime import date
from types import SimpleNamespace

import pytest
from app.modules.volunteer.eligibility_index import EligibilityIndex

from tests.unit.test_support_retirement import legacy as legacy_fixture


@pytest.fixture
def legacy():
    yield from legacy_fixture.__wrapped__()


def test_historical_support_scope_cannot_authorize_foreign_students(legacy):
    db, _, cid, gid, semester, _, foreign, _, support = legacy
    task = SimpleNamespace(
        group_id=gid, college_id=cid, semester_id=semester.id, inspection_date=date(2026, 9, 7)
    )
    for scope in ({"class_mode": "ALL_AUTHORIZED", "course_type_ids": ["1"]}, None):
        support.scope_snapshot = scope
        db.commit()
        assert not EligibilityIndex(db, [foreign.id], [task]).member_allowed(task, foreign.id)
