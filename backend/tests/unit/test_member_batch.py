import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.volunteer.member_models import VolunteerGroupMember
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_batch_preview_is_not_a_write_and_commit_does_not_partially_add(campus):
    from app.modules.volunteer.member_batch import GroupMemberBatchService
    config, db, admin, a, b, semester, group, another, own, foreign = prepare(campus)
    service = GroupMemberBatchService(db, admin, int(a["id"]), int(group["id"]))
    body = {"semester_id": str(semester.id), "student_nos": [own.student_no],
            "effective_from": "2026-09-07", "effective_to": "2027-01-01"}
    preview = service.preview(body)
    assert db.scalar(select(func.count()).select_from(VolunteerGroupMember)) == 0
    with pytest.raises((ConflictError, NotFoundError)):
        service.commit({**body, "student_nos": [own.student_no, foreign.student_no]}, preview["revision"])
    assert db.scalar(select(func.count()).select_from(VolunteerGroupMember)) == 0
    assert service.commit(body, service.preview(body)["revision"])["created"] == 1
    with pytest.raises(ConflictError):
        service.commit(body, preview["revision"])
    assert db.scalar(select(func.count()).select_from(VolunteerGroupMember)) == 1
