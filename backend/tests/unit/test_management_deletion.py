from datetime import datetime

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.inspection.models import InspectionTask, TaskDeadlineAssessment
from app.modules.inspection.scoped_service import ScopedInspectionService
from app.modules.volunteer.models import VolunteerGroup
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_referenced_group_is_removed_and_restorable_without_erasing_members(campus):
    from app.modules.volunteer.member_service import GroupMemberService

    config, db, admin, a, _, sem, group, _, own, _ = prepare(campus)
    gid, cid = int(group["id"]), int(a["id"])
    GroupMemberService(db, admin, cid, gid).create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-07",
            "effective_to": "2027-01-31",
        }
    )
    row = db.get(VolunteerGroup, gid)
    plan = config.deletion_preview(admin, cid, "group", gid)
    assert plan["mode"] == "RETAIN_HISTORY"
    config.delete_group(admin, cid, gid, row.lock_version, plan["revision"])
    assert db.get(VolunteerGroup, gid).deleted_at is not None
    assert all(item["id"] != str(gid) for item in config.list_groups(admin, cid))
    with pytest.raises(NotFoundError):
        GroupMemberService(db, admin, cid, gid).members(sem.id)
    row = config.restore_deleted(admin, cid, "group", gid, row.lock_version)
    assert row["status"] == "INACTIVE"
    assert len(GroupMemberService(db, admin, cid, gid).members(sem.id)) == 1


def test_builtin_type_can_be_removed_but_identity_survives(campus):
    config, db, admin, _, a, _ = campus
    cid = int(a["id"])
    kind = db.scalar(
        select(CourseType).where(CourseType.college_id == cid, CourseType.builtin_key == "regular")
    )
    plan = config.deletion_preview(admin, cid, "course_type", kind.id)
    config.delete_type(admin, cid, kind.id, kind.lock_version, plan["revision"])
    assert db.get(CourseType, kind.id).builtin_key == "regular"
    assert all(row["id"] != str(kind.id) for row in config.list_types(admin, cid))
    config.restore_deleted(admin, cid, "course_type", kind.id, kind.lock_version)
    assert db.get(CourseType, kind.id).deleted_at is None


def test_task_with_deadline_history_is_hidden_not_destroyed(campus):
    _, db, admin, a, _, _, _, _, _, _ = prepare(campus)
    task = db.scalar(select(InspectionTask))
    db.add(
        TaskDeadlineAssessment(
            task_id=task.id,
            deadline_at_snapshot=datetime(2026, 9, 7),
            result="OVERDUE_UNEXECUTED",
            evaluated_at=datetime(2026, 9, 8),
        )
    )
    db.commit()
    svc = ScopedInspectionService(db, admin, int(a["id"]))
    plan = svc.deletion_preview(admin, [task.id])
    assert plan["retained_ids"] == [str(task.id)]
    with pytest.raises(ConflictError):
        svc.delete_tasks(admin, [task.id], deletion_revision="0" * 64)
    svc.delete_tasks(admin, [task.id], deletion_revision=plan["revision"])
    assert db.get(InspectionTask, task.id).deleted_at is not None
    assert db.scalar(select(TaskDeadlineAssessment.id)) is not None
    filters = dict(
        semester_id=None,
        inspection_date=None,
        week_no=None,
        inspection_type=None,
        include_canceled=True,
    )
    assert svc.list_tasks(admin, PageParams(1, 10), **filters)["total"] == 0
    assert svc.list_tasks(admin, PageParams(1, 10), deleted_only=True, **filters)["total"] == 1
    svc.restore_deleted_task(admin, task.id, task.lock_version)
    assert db.get(InspectionTask, task.id).deleted_at is None


def test_pending_future_task_blocks_group_deletion(campus):
    from datetime import timedelta

    from app.modules.identity.role_scope import business_today

    config, db, admin, a, _, _, group, _, _, _ = prepare(campus)
    task = db.scalar(select(InspectionTask))
    task.group_id = int(group["id"])
    task.inspection_date = business_today() + timedelta(days=1)
    db.commit()
    plan = config.deletion_preview(admin, int(a["id"]), "group", int(group["id"]))
    assert not plan["can_delete"]
    with pytest.raises(ConflictError, match="待执行"):
        config.delete_group(
            admin, int(a["id"]), int(group["id"]), group["lock_version"], plan["revision"]
        )
    assert db.get(VolunteerGroup, int(group["id"])).deleted_at is None


def test_deleted_name_can_be_reused_and_restored_with_another_name(campus):
    config, db, admin, _, a, _ = campus
    cid = int(a["id"])
    kind = db.scalar(
        select(CourseType).where(CourseType.college_id == cid, CourseType.builtin_key == "regular")
    )
    plan = config.deletion_preview(admin, cid, "course_type", kind.id)
    config.delete_type(admin, cid, kind.id, kind.lock_version, plan["revision"])
    config.create_type(admin, cid, {"name": kind.name})
    restored = config.restore_deleted(
        admin, cid, "course_type", kind.id, kind.lock_version, "原普通课"
    )
    assert restored["name"] == "原普通课"


def test_cross_college_mixed_task_deletion_is_atomic(campus):
    _, db, admin, a, b, sem, _, _, _, _ = prepare(campus)
    own = db.scalar(select(InspectionTask))
    other = InspectionTask(
        task_key="FOREIGN_DELETE",
        college_id=int(b["id"]),
        semester_id=sem.id,
        inspection_date=own.inspection_date,
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
    )
    db.add(other)
    db.commit()
    svc = ScopedInspectionService(db, admin, int(a["id"]))
    with pytest.raises(NotFoundError):
        svc.delete_tasks(admin, [own.id, other.id])
    assert db.get(InspectionTask, own.id) is not None
    assert db.get(InspectionTask, other.id) is not None


def test_group_restore_does_not_resurrect_its_grants(campus):
    from app.modules.organization.models import ScopedGrant

    config, db, admin, a, _, _, group, _, _, _ = prepare(campus)
    cid, gid = int(a["id"]), int(group["id"])
    grant = ScopedGrant(
        college_id=cid,
        user_id=admin.id,
        granted_by=admin.id,
        owner_group_id=gid,
        actions=["volunteer.member.manage"],
        status="ACTIVE",
    )
    db.add(grant)
    db.commit()
    row = db.get(VolunteerGroup, gid)
    plan = config.deletion_preview(admin, cid, "group", gid)
    config.delete_group(admin, cid, gid, row.lock_version, plan["revision"])
    assert grant.status == "REVOKED"
    config.restore_deleted(admin, cid, "group", gid, row.lock_version)
    assert grant.status == "REVOKED"


def test_archived_task_deletion_is_reversible_and_skips_deadline_settlement(campus):
    _, db, admin, a, _, sem, _, _, _, _ = prepare(campus)
    task = db.scalar(select(InspectionTask))
    sem.status = "ARCHIVED"
    db.commit()
    svc = ScopedInspectionService(db, admin, int(a["id"]))
    plan = svc.deletion_preview(admin, [task.id])
    assert plan["permanent_ids"] == []
    svc.delete_tasks(admin, [task.id], deletion_revision=plan["revision"])
    assert svc._repo.list_unsettled_task_ids(sem.id) == []
    svc.restore_deleted_task(admin, task.id, task.lock_version)
    assert sem.status == "ARCHIVED" and task.deleted_at is None
