from datetime import date

import pytest
from app.core.exceptions import ConflictError
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.organization.impact_models import ConfigurationImpactItem
from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture
def working(monkeypatch):
    source = campus_fixture.__wrapped__()
    campus = next(source)
    try:
        db, actor, college, semester, group, student, teaching, other = arrange(campus, monkeypatch)
        cid, gid = int(college["id"]), int(group["id"])
        sampler = GroupSamplingService(db, actor, cid, gid)
        body = {
            "semester_id": str(semester.id),
            "date_from": "2026-09-07",
            "date_to": "2026-09-07",
            "counts": {str(student.administrative_class_id): 1},
            "draw_id": "workflow",
        }
        generated = sampler.generate(body, sampler.preview(body)["selection_revision"])
        task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
        monkeypatch.setattr(
            "app.modules.organization.future_impact.business_today", lambda: date(2026, 9, 7)
        )
        yield campus[0], db, actor, cid, gid, semester, task, student, other
    finally:
        source.close()


def test_identical_rules_do_not_create_versions_or_impacts(working):
    service, db, actor, cid, gid, _, _, _, _ = working
    group = db.get(VolunteerGroup, gid)
    before = service._dto(group)
    versions = db.scalar(select(func.count()).select_from(GroupConfigVersion))
    result = service.publish_group(
        actor, cid, gid, {"lock_version": group.lock_version, **before["configuration"]}
    )
    assert result["lock_version"] == before["lock_version"]
    assert db.scalar(select(func.count()).select_from(GroupConfigVersion)) == versions
    assert db.scalar(select(func.count()).select_from(ConfigurationImpactItem)) == 0


def test_legacy_missing_optional_defaults_are_not_a_rule_change(working):
    service, db, actor, cid, gid, _, task, _, _ = working
    group = db.get(VolunteerGroup, gid)
    stored = db.get(GroupConfigVersion, task.group_config_version_id)
    original = dict(stored.configuration)
    stored.configuration = {
        k: v
        for k, v in original.items()
        if k not in {"class_mode", "class_ids", "teaching_class_overrides"}
    }
    db.commit()
    version = group.config_version
    service.publish_group(actor, cid, gid, {"lock_version": group.lock_version, **original})
    assert group.config_version == version


def test_renaming_does_not_require_task_confirmation_or_create_impacts(working):
    service, db, actor, cid, gid, _, task, _, kind = working
    group = db.get(VolunteerGroup, gid)
    service.update_group(actor, cid, gid, {"lock_version": group.lock_version, "name": "新名称"})
    service.update_type(
        actor, cid, int(kind["id"]), {"lock_version": kind["lock_version"], "name": "新分类名称"}
    )
    assert db.scalar(select(func.count()).select_from(ConfigurationImpactItem)) == 0
    assert task.canceled_at is None


def test_real_rule_change_still_requires_impact_confirmation(working):
    service, db, actor, cid, gid, _, _, _, _ = working
    group = db.get(VolunteerGroup, gid)
    with pytest.raises(ConflictError):
        service.publish_group(
            actor,
            cid,
            gid,
            {
                "lock_version": group.lock_version,
                **service._dto(group)["configuration"],
                "daily_limit": 2,
            },
        )


def test_semester_rules_can_be_updated_without_rewriting_default_or_tasks(working):
    from app.modules.volunteer.preparation_models import (
        GroupSemesterPreparation,
        semester_group_config,
    )

    service, db, actor, cid, gid, semester, task, _, _ = working
    group = db.get(VolunteerGroup, gid)
    default = service._dto(group)["configuration"]
    old_config_id = task.group_config_version_id
    db.add(
        GroupSemesterPreparation(
            college_id=cid,
            group_id=gid,
            semester_id=semester.id,
            source_semester_id=semester.id,
            config_id=old_config_id,
        )
    )
    db.commit()
    revision = service.configuration_impact(actor, cid, "group", gid, semester_id=semester.id)[
        "revision"
    ]
    service.publish_group(
        actor,
        cid,
        gid,
        {
            "lock_version": group.lock_version,
            **default,
            "daily_limit": 2,
            "future_impact_revision": revision,
        },
        semester_id=semester.id,
    )
    assert semester_group_config(db, group, semester.id).configuration["daily_limit"] == 2
    assert service._dto(group)["configuration"] == default
    assert task.group_config_version_id == old_config_id
    semester.status = "ARCHIVED"
    db.commit()
    with pytest.raises(ConflictError):
        service.publish_group(
            actor,
            cid,
            gid,
            {"lock_version": group.lock_version, **default},
            semester_id=semester.id,
        )


def test_automatic_resolution_closes_changed_assignment_but_not_same_assignment(working):
    from app.modules.organization.impact_service import capture_impacts, close_resolved_impacts

    _, db, actor, cid, gid, _, task, _, _ = working
    assignment = InspectionAssignment(
        task_id=task.id,
        volunteer_user_id=actor.id,
        assigned_by=actor.id,
        assign_method="MANUAL",
        lock_version=0,
    )
    db.add(assignment)
    db.flush()
    capture_impacts(db, cid, "group", gid, 100, task_ids=[task.id])
    close_resolved_impacts(db, actor.id, [task.id])
    row = db.scalar(select(ConfigurationImpactItem))
    assert row.status == "OPEN"
    assignment.revoked_at = __import__("app.core.database", fromlist=["utcnow"]).utcnow()
    db.flush()
    db.add(
        InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=actor.id,
            assigned_by=actor.id,
            assign_method="MANUAL",
            lock_version=0,
        )
    )
    db.flush()
    close_resolved_impacts(db, actor.id, [task.id])
    assert row.status == "REASSIGNED"
    assert row.decided_by == actor.id
    assert row.decision["automatic"] is True


def test_member_preview_survives_unrelated_college_configuration_change(working):
    from app.modules.volunteer.member_batch import GroupMemberBatchService

    service, _, actor, cid, gid, semester, _, student, _ = working
    members = GroupMemberBatchService(service.db, actor, cid, gid)
    body = {
        "semester_id": str(semester.id),
        "student_nos": [student.student_no],
        "effective_from": "2026-09-07",
        "effective_to": "2027-01-01",
    }
    preview = members.preview(body)
    service.create_type(actor, cid, {"name": "与成员无关的新分类"})
    group = service.db.get(VolunteerGroup, gid)
    service.update_group(actor, cid, gid, {"lock_version": group.lock_version, "name": "只改名称"})
    assert members.commit(body, preview["revision"])["created"] == 1


def test_task_cancellation_closes_impacts_without_second_registration(working):
    from app.modules.inspection.schemas import TaskCancelRequest
    from app.modules.inspection.scoped_service import ScopedInspectionService
    from app.modules.organization.impact_service import capture_impacts

    _, db, actor, cid, gid, _, task, _, _ = working
    capture_impacts(db, cid, "group", gid, 99, task_ids=[task.id])
    ScopedInspectionService(db, actor, cid).cancel_task(
        actor,
        task.id,
        TaskCancelRequest(lock_version=task.lock_version, reason="本地取消回归"),
        None,
    )
    assert db.scalar(select(ConfigurationImpactItem)).status == "CANCEL"


def test_default_rule_update_does_not_create_impacts_for_pinned_semester(working):
    from app.modules.volunteer.preparation_models import GroupSemesterPreparation

    service, db, actor, cid, gid, semester, task, _, _ = working
    group = db.get(VolunteerGroup, gid)
    old_config = task.group_config_version_id
    db.add(
        GroupSemesterPreparation(
            college_id=cid,
            group_id=gid,
            semester_id=semester.id,
            source_semester_id=semester.id,
            config_id=old_config,
        )
    )
    db.commit()
    service.publish_group(
        actor,
        cid,
        gid,
        {
            "lock_version": group.lock_version,
            **service._dto(group)["configuration"],
            "daily_limit": 2,
        },
    )
    assert task.group_config_version_id == old_config
    assert db.scalar(select(func.count()).select_from(ConfigurationImpactItem)) == 0


def test_semester_publication_keeps_scope_and_optimistic_lock_checks(working):
    from app.core.exceptions import NotFoundError, PermissionDeniedError
    from app.modules.identity.models import UserAccount
    from app.modules.identity.service import CurrentUser

    service, db, actor, cid, gid, semester, _, _, _ = working
    group = db.get(VolunteerGroup, gid)
    body = {"lock_version": group.lock_version, **service._dto(group)["configuration"]}
    with pytest.raises(ConflictError):
        service.publish_group(
            actor,
            cid,
            gid,
            {**body, "lock_version": body["lock_version"] + 1},
            semester_id=semester.id,
        )
    user = UserAccount(display_name="无管理授权", status="ACTIVE")
    db.add(user)
    db.commit()
    outsider = CurrentUser(user.id, None, user.display_name, "ACTIVE", [], [])
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        service.publish_group(outsider, cid, gid, body, semester_id=semester.id)
