from datetime import date

import pytest
from app.core.exceptions import ConflictError
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionAssignment
from app.modules.volunteer.member_models import VolunteerGroupMember
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_rules import prepared_task


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_member_revocation_requires_confirmation_and_preserves_assignment(campus, monkeypatch):
    import app.modules.volunteer.member_service as module

    db, task, own, _, service, _ = prepared_task(campus)
    monkeypatch.setattr(module, "business_today", lambda: date(2026, 9, 7), raising=False)
    user = UserAccount(student_id=own.id, display_name="test volunteer", status="ACTIVE")
    db.add_all([user, task])
    db.flush()
    assignment = InspectionAssignment(
        task_id=task.id, volunteer_user_id=user.id, assigned_by=campus[2].id, assign_method="MANUAL"
    )
    db.add(assignment)
    db.commit()
    member = db.scalar(
        select(VolunteerGroupMember).where(VolunteerGroupMember.student_id == own.id)
    )
    with pytest.raises(ConflictError):
        service.revoke(member.id, member.lock_version)
    db.refresh(member)
    assert member.status == "ACTIVE"
    result = service.revoke(member.id, member.lock_version, confirm_future_assignments=True)
    assert result["retained_future_task_ids"] == [str(task.id)]
    db.refresh(assignment)
    assert assignment.revoked_at is None


def test_duplicate_inactive_member_start_is_explicit_conflict(campus):
    db, task, own, _, service, _ = prepared_task(campus)
    member = db.scalar(
        select(VolunteerGroupMember).where(VolunteerGroupMember.student_id == own.id)
    )
    service.revoke(member.id, member.lock_version)
    with pytest.raises(ConflictError):
        service.create(
            {
                "student_id": str(own.id),
                "semester_id": str(task.semester_id),
                "effective_from": "2026-09-07",
                "effective_to": "2026-09-14",
            }
        )


def test_member_can_reactivate_without_duplicate_and_reject_stale_or_past_edit(campus, monkeypatch):
    import app.modules.volunteer.member_service as module

    db, task, own, _, service, _ = prepared_task(campus)
    monkeypatch.setattr(module, "business_today", lambda: date(2026, 9, 8))
    member = db.scalar(
        select(VolunteerGroupMember).where(VolunteerGroupMember.student_id == own.id)
    )
    inactive = service.revoke(member.id, member.lock_version)
    values = {
        "effective_from": member.effective_from,
        "effective_to": member.effective_to,
        "lock_version": inactive["lock_version"],
        "status": "ACTIVE",
    }
    result = service.update(member.id, values)
    assert result["status"] == "ACTIVE"
    assert result["id"] == str(member.id)
    with pytest.raises(ConflictError):
        service.update(member.id, values)
    with pytest.raises(ConflictError):
        service.update(
            member.id,
            {**values, "lock_version": result["lock_version"], "effective_from": date(2026, 9, 6)},
        )
    assert service.impact(member.id)["retained_future_task_ids"] == []


def test_member_candidates_only_include_college_students(campus):
    _, task, own, foreign, service, _ = prepared_task(campus)
    start, end = date(2026, 9, 7), date(2026, 9, 14)
    assert [r["id"] for r in service.candidates(task.semester_id, start, end)] == [str(own.id)]
    ids = {r["id"] for r in service.candidates(task.semester_id, start, end)}
    assert ids == {str(own.id)}
    assert service.candidates(task.semester_id, start, date(2026, 9, 15)) == [
        r for r in service.candidates(task.semester_id, start, end) if r["id"] == str(own.id)
    ]
