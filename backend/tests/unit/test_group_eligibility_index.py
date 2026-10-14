from datetime import date

import pytest
from sqlalchemy import event

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_eligibility_index_is_batched_and_rejects_foreign_without_support(campus):
    from types import SimpleNamespace

    from app.modules.volunteer.eligibility_index import EligibilityIndex
    from app.modules.volunteer.member_service import GroupMemberService

    _, db, admin, a, _, sem, group, _, own, foreign = prepare(campus)
    service = GroupMemberService(db, admin, int(a["id"]), int(group["id"]))
    service.create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-01",
            "effective_to": "2027-01-31",
        }
    )
    task = SimpleNamespace(
        group_id=int(group["id"]),
        college_id=int(a["id"]),
        semester_id=sem.id,
        inspection_date=date(2026, 9, 7),
    )
    statements = []

    def count(*args):
        statements.append(args[2])

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        index = EligibilityIndex(db, [own.id, foreign.id], [task], lock=True)
        baseline = len(statements)
        for _ in range(100):
            assert index.member_allowed(task, own.id)
            assert not index.member_allowed(task, foreign.id)
            assert index.class_id(own.id, task.inspection_date) == own.administrative_class_id
        assert len(statements) == baseline
        assert baseline <= 4
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
