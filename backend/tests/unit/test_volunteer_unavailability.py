import pytest
from app.core.exceptions import ConflictError
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_assignment_confirmation_plan import prepared_fixture


@pytest.fixture(name="prepared")
def fixture(monkeypatch):
    yield from prepared_fixture.__wrapped__(monkeypatch)


def test_approved_unavailability_blocks_all_groups_and_invalidates_old_plan(prepared, monkeypatch):
    from app.modules.inspection.scheduling.loader import load_snapshot
    from app.modules.inspection.service import InspectionService
    from app.modules.volunteer.models import VolunteerGroup
    from app.modules.volunteer.unavailability_service import UnavailabilityService

    db, plans, sem, tasks, user = prepared
    monkeypatch.setattr(InspectionService, "_lock_day_anchors", lambda *args: None)
    preview = plans.preview({"semester_id": str(sem.id), "task_ids": tasks})
    task = db.get(InspectionTask, int(tasks[0]))
    service = UnavailabilityService(db, plans.actor, plans.cid, plans.gid)
    request = service.create(
        {
            "student_id": str(user.student_id),
            "semester_id": str(sem.id),
            "starts_at": "2026-09-07T07:00:00+08:00",
            "ends_at": "2026-09-07T09:00:00+08:00",
            "reason": "请假",
        }
    )
    assert load_snapshot(db, sem, [task], [user.id]).tasks[0].candidates == frozenset({user.id})
    service.decide(
        int(request["id"]),
        {
            "lock_version": 1,
            "status": "APPROVED",
            "impact_revision": service.impact(int(request["id"]))["revision"],
        },
    )
    snapshot = load_snapshot(db, sem, [task], [user.id])
    assert not snapshot.tasks[0].candidates
    assert snapshot.static_failures[task.id] == "VOLUNTEER_UNAVAILABLE"
    # The stored source group is not part of the scheduling predicate.
    from app.modules.volunteer.unavailability_models import VolunteerUnavailability

    row = db.get(VolunteerUnavailability, int(request["id"]))
    other = VolunteerGroup(
        college_id=plans.cid,
        name="another origin",
        normalized_name="another origin",
        owner_user_id=plans.actor.id,
    )
    db.add(other)
    db.flush()
    row.group_id = other.id
    db.commit()
    assert not load_snapshot(db, sem, [task], [user.id]).tasks[0].candidates
    with pytest.raises(ConflictError):
        plans.commit(
            preview["id"], {"revision": preview["revision"], "confirmations": preview["assigned"]}
        )


def test_approval_keeps_assignment_and_creates_impact_then_cancel_restores_availability(
    prepared, monkeypatch
):
    from datetime import date

    from app.modules.inspection.models import InspectionAssignment
    from app.modules.inspection.scheduling.loader import load_snapshot
    from app.modules.inspection.service import InspectionService
    from app.modules.organization.impact_models import ConfigurationImpactItem
    from app.modules.volunteer.unavailability_service import UnavailabilityService

    db, plans, sem, tasks, user = prepared
    monkeypatch.setattr(InspectionService, "_lock_day_anchors", lambda *args: None)
    monkeypatch.setattr(
        "app.modules.organization.future_impact.business_today", lambda: date(2026, 9, 7)
    )
    preview = plans.preview({"semester_id": str(sem.id), "task_ids": tasks})
    plans.commit(
        preview["id"], {"revision": preview["revision"], "confirmations": preview["assigned"]}
    )
    assignment = db.scalar(select(InspectionAssignment))
    original = (assignment.id, assignment.volunteer_user_id, assignment.revoked_at)
    service = UnavailabilityService(db, plans.actor, plans.cid, plans.gid)
    request = service.create(
        {
            "student_id": str(user.student_id),
            "semester_id": str(sem.id),
            "starts_at": "2026-09-07T07:00:00+08:00",
            "ends_at": "2026-09-07T09:00:00+08:00",
        }
    )
    impact = service.impact(int(request["id"]))
    assert impact["retained_assignment_count"] == 1
    approved = service.decide(
        int(request["id"]),
        {"lock_version": 1, "status": "APPROVED", "impact_revision": impact["revision"]},
    )
    assert (assignment.id, assignment.volunteer_user_id, assignment.revoked_at) == original
    stored = db.scalar(
        select(ConfigurationImpactItem).where(
            ConfigurationImpactItem.source_kind == "unavailability"
        )
    )
    assert stored.task_id == int(tasks[0]) and stored.status == "OPEN"
    service.decide(
        int(request["id"]), {"lock_version": approved["lock_version"], "status": "CANCELED"}
    )
    task = db.get(InspectionTask, int(tasks[0]))
    assert user.id in load_snapshot(db, sem, [task], [user.id]).tasks[0].candidates


def test_half_open_interval_and_stale_approval(prepared, monkeypatch):
    from app.modules.inspection.scheduling.loader import load_snapshot
    from app.modules.inspection.service import InspectionService
    from app.modules.volunteer.unavailability_service import UnavailabilityService

    db, plans, sem, tasks, user = prepared
    monkeypatch.setattr(InspectionService, "_lock_day_anchors", lambda *args: None)
    service = UnavailabilityService(db, plans.actor, plans.cid, plans.gid)
    request = service.create(
        {
            "student_id": str(user.student_id),
            "semester_id": str(sem.id),
            "starts_at": "2026-09-07T08:30:00+08:00",
            "ends_at": "2026-09-07T09:00:00+08:00",
        }
    )
    with pytest.raises(ConflictError):
        service.decide(
            int(request["id"]),
            {"lock_version": 1, "status": "APPROVED", "impact_revision": "0" * 64},
        )
    service.decide(
        int(request["id"]),
        {
            "lock_version": 1,
            "status": "APPROVED",
            "impact_revision": service.impact(int(request["id"]))["revision"],
        },
    )
    task = db.get(InspectionTask, int(tasks[0]))
    assert user.id in load_snapshot(db, sem, [task], [user.id]).tasks[0].candidates


def test_self_request_cannot_impersonate_or_approve(prepared, monkeypatch):
    from dataclasses import replace

    from app.core.exceptions import NotFoundError, PermissionDeniedError
    from app.modules.inspection.service import InspectionService
    from app.modules.volunteer.unavailability_service import UnavailabilityService

    db, plans, sem, tasks, user = prepared
    monkeypatch.setattr(InspectionService, "_lock_day_anchors", lambda *args: None)
    actor = replace(plans.actor, id=user.id, roles=["VOLUNTEER"], permissions=[])
    own = UnavailabilityService(db, actor, plans.cid, plans.gid)
    body = {
        "student_id": str(user.student_id),
        "semester_id": str(sem.id),
        "starts_at": "2026-09-07T07:00:00+08:00",
        "ends_at": "2026-09-07T09:00:00+08:00",
    }
    with pytest.raises(PermissionDeniedError):
        own.create({**body, "student_id": str(user.student_id + 1)}, own=True)
    created = own.create(body, own=True)
    assert len(own.list(sem.id, own=True)["items"]) == 1
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        own.decide(int(created["id"]), {"lock_version": 1, "status": "APPROVED"}, own=True)
    own.decide(int(created["id"]), {"lock_version": 1, "status": "CANCELED"}, own=True)
    assert own.list(sem.id, own=True)["items"][0]["status"] == "CANCELED"
