from datetime import date
from types import SimpleNamespace

import pytest
from app.core.exceptions import ConflictError
from app.modules.volunteer.eligibility_index import EligibilityIndex
from app.modules.volunteer.member_batch import GroupMemberBatchService
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport
from app.modules.volunteer.member_service import GroupMemberService
from sqlalchemy import event

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture
def legacy():
    fixture = campus_fixture.__wrapped__()
    campus = next(fixture)
    try:
        _, db, actor, a, _, semester, group, _, own, foreign = prepare(campus)
        cid, gid = int(a["id"]), int(group["id"])
        fields = dict(
            college_id=cid,
            group_id=gid,
            student_id=foreign.id,
            semester_id=semester.id,
            effective_from=date(2026, 9, 1),
            effective_to=date(2027, 1, 31),
        )
        support = VolunteerGroupSupport(
            **fields,
            authorized_by=actor.id,
            scope_snapshot={"course_type_ids": ["1"], "class_mode": "ALL_AUTHORIZED"},
        )
        member = VolunteerGroupMember(**fields)
        db.add_all([support, member])
        db.commit()
        yield db, actor, cid, gid, semester, own, foreign, member, support
    finally:
        fixture.close()


def test_legacy_support_does_not_allow_new_cross_college_members_or_batch_reuse(legacy):
    db, actor, cid, gid, semester, _, foreign, _, _ = legacy
    members = GroupMemberService(db, actor, cid, gid)
    body = {
        "student_id": str(foreign.id),
        "semester_id": str(semester.id),
        "effective_from": "2026-09-01",
        "effective_to": "2027-01-31",
    }
    with pytest.raises(ConflictError, match="本学院"):
        members.create(body)
    with pytest.raises(ConflictError, match="本学院"):
        GroupMemberBatchService(db, actor, cid, gid).preview(
            {
                "semester_id": str(semester.id),
                "student_nos": [foreign.student_no],
                "effective_from": "2026-09-01",
                "effective_to": "2027-01-31",
                "skip_existing": True,
            }
        )


def test_scheduling_never_reads_support_table_or_accepts_legacy_foreign_member(legacy):
    db, _, cid, gid, semester, own, foreign, _, support = legacy
    task = SimpleNamespace(
        group_id=gid, college_id=cid, semester_id=semester.id, inspection_date=date(2026, 9, 7)
    )
    statements = []

    def observe(*args):
        statements.append(args[2].lower())

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        index = EligibilityIndex(db, [own.id, foreign.id], [task], lock=True)
        assert not index.member_allowed(task, foreign.id)
        assert not any("volunteer_group_support" in s for s in statements)
        assert support.status == "ACTIVE"
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)


def test_candidates_are_local_and_legacy_member_can_still_be_revoked(legacy):
    db, actor, cid, gid, semester, own, foreign, member, _ = legacy
    service = GroupMemberService(db, actor, cid, gid)
    assert [
        r["id"] for r in service.candidates(semester.id, date(2026, 9, 1), date(2027, 1, 31))
    ] == [str(own.id)]
    assert service.revoke(member.id, member.lock_version)["status"] == "INACTIVE"


def test_support_http_routes_are_removed():
    from app.modules.volunteer.member_router import router

    assert not any("support-authorizations" in route.path for route in router.routes)


def test_organization_count_excludes_historical_foreign_members(legacy):
    from app.modules.volunteer.overview import semester_overview

    db, actor, cid, gid, semester, _, _, _, _ = legacy
    result = semester_overview(db, actor, cid, semester.id, date(2026, 9, 7))
    assert result["items"][str(gid)]["member_count"] == 0
