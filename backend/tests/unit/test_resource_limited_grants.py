import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.scoped_service import ScopedInspectionService
from app.modules.volunteer.member_service import GroupMemberService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_group_grant_does_not_become_college_wide_permission(campus, monkeypatch):
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    teacher = campus[3]
    config = campus[0]
    grant = {
        "user_id": str(teacher.id),
        "actions": ["volunteer.group.read", "volunteer.member.manage", "inspection.read"],
        "resource_scope": {"kind": "GROUPS", "ids": [group["id"]]},
    }
    grant["preview_revision"] = config.preview_grant(admin, int(a["id"]), grant)["revision"]
    config.create_grant(admin, int(a["id"]), grant)
    body = {"semester_id": str(sem.id), "date_from": "2026-09-07", "date_to": "2026-09-07",
            "counts": {str(own.administrative_class_id): 1}, "draw_id": "scope"}
    sampler = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    generated = sampler.generate(body, sampler.preview(body)["selection_revision"])
    visible = ScopedInspectionService(db, teacher, int(a["id"])).list_tasks(teacher, PageParams(1, 20),
        semester_id=sem.id, inspection_date=None, week_no=None, inspection_type=None, include_canceled=False)
    assert visible["total"] == 1
    assert visible["items"][0]["id"] == generated.assignable_task_ids[0]
    groups = config.list_groups(teacher, int(a["id"]))
    assert [item["id"] for item in groups] == [group["id"]]
    other = config.create_group(admin, int(a["id"]), {"name": "not granted", "owner_user_id": str(admin.id)})
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        GroupMemberService(db, teacher, int(a["id"]), int(other["id"])).members(sem.id)
    # Legacy college-list adapters must not promote a group-only grant.
    from app.modules.identity.management_scope import management_college_ids
    assert management_college_ids(db, teacher, "inspection.read") == frozenset()


def test_grant_preview_rejects_changed_scope_and_group_cannot_expand_it(campus, monkeypatch):
    from app.core.exceptions import ConflictError
    from app.modules.volunteer.models import VolunteerGroup
    db, admin, a, sem, group, own, teaching, other = arrange(campus, monkeypatch)
    config, _, _, teacher, *_ = campus
    cid, gid = int(a["id"]), int(group["id"])
    grant = {"user_id": str(teacher.id), "actions": ["volunteer.group.read", "volunteer.config.publish"],
             "resource_scope": {"kind": "GROUPS", "ids": [group["id"]]}}
    old_preview = config.preview_grant(admin, cid, grant)["revision"]
    row = db.get(VolunteerGroup, gid)
    current = config.publish_group(admin, cid, gid, {"lock_version": row.lock_version,
                                                   "course_type_ids": [str(teaching.course_type_id), other["id"]]})
    with pytest.raises(ConflictError):
        config.create_grant(admin, cid, {**grant, "preview_revision": old_preview})
    preview = config.preview_grant(admin, cid, grant)
    config.create_grant(admin, cid, {**grant, "preview_revision": preview["revision"]})
    references = config.group_references(teacher, cid, gid)
    assert {item["id"] for item in references["types"]} == {str(teaching.course_type_id), other["id"]}
    extra = config.create_type(admin, cid, {"name": "not in frozen grant"})
    with pytest.raises(PermissionDeniedError):
        config.publish_group(teacher, cid, gid, {"lock_version": current["lock_version"],
                                               "course_type_ids": [extra["id"]]})


def test_group_photo_access_does_not_leak_sibling_group(campus, monkeypatch):
    from app.core.database import utcnow
    from app.modules.file.models import FileObject
    from app.modules.file.service import FileService
    from app.modules.inspection.models import InspectionSubmission, InspectionTask, SubmissionFile
    from sqlalchemy import select
    db, admin, a, sem, group, own, teaching, other = arrange(campus, monkeypatch)
    config, _, _, teacher, *_ = campus
    grant = {"user_id": str(teacher.id), "actions": ["submission.review"],
             "resource_scope": {"kind": "GROUPS", "ids": [group["id"]]}}
    config.create_grant(admin, int(a["id"]), {**grant, "preview_revision": config.preview_grant(admin, int(a["id"]), grant)["revision"]})
    sampler = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {"semester_id": str(sem.id), "date_from": "2026-09-07", "date_to": "2026-09-07",
            "counts": {str(own.administrative_class_id): 1}, "draw_id": "photos"}
    result = sampler.generate(body, sampler.preview(body)["selection_revision"])
    own_task = db.get(InspectionTask, int(result.assignable_task_ids[0]))
    other_task = db.scalar(select(InspectionTask).where(InspectionTask.id != own_task.id))
    photos = []
    for task in (own_task, other_task):
        sub = InspectionSubmission(task_id=task.id, attempt_no=1, volunteer_user_id=admin.id,
            roster_version=1, result="NORMAL", review_status="APPROVED", submitted_at=utcnow())
        photo = FileObject(object_key=f"limited/{task.id}.jpg", category="SUBMISSION_PHOTO",
            content_type="image/jpeg", size_bytes=1, sha256="0"*64, uploader_user_id=admin.id, status="READY")
        db.add_all([sub, photo]); db.flush()
        db.add(SubmissionFile(submission_id=sub.id, file_id=photo.id)); photos.append(photo)
    db.commit()
    service = FileService(db)
    assert service.can_access(teacher, photos[0])
    assert not service.can_access(teacher, photos[1])
