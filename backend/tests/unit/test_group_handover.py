import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.identity.resource_scope import resolve_scope
from app.modules.organization.models import ScopedGrant
from app.modules.volunteer.handover import GroupHandoverService, permission_sources

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_handover_preserves_independent_sources_and_is_atomic(campus):
    service, db, admin, reader, a, _ = campus
    cid = int(a["id"])
    course_type = next(t for t in service.list_types(admin, cid) if t["name"] == "普通课")
    group = service.create_group(admin, cid, {"name": "检查组", "owner_user_id": str(admin.id)})
    gid = int(group["id"])
    published = service.publish_group(
        admin,
        cid,
        gid,
        {"lock_version": group["lock_version"], "course_type_ids": [course_type["id"]]},
    )
    service.update_group(
        admin, cid, gid, {"lock_version": published["lock_version"], "status": "ACTIVE"}
    )
    independent = service.create_grant(
        admin, cid, {"user_id": str(reader.id), "actions": ["academic.read"]}
    )
    handover = GroupHandoverService(db, admin, cid, gid)
    body = {"owner_user_id": str(reader.id), "reason": "新负责人任命"}
    old = handover.preview(body)
    result = handover.confirm({**body, "revision": old["revision"]})
    assert result["owner_user_id"] == str(reader.id)
    assert resolve_scope(db, reader, cid, "inspection.read").permits_group(gid)
    sources = permission_sources(db, reader.id, cid)
    assert {r["kind"] for r in sources} == {"EXPLICIT_GRANT", "GROUP_OWNER"}
    with pytest.raises(ConflictError):
        handover.confirm({**body, "revision": old["revision"]})
    back = {"owner_user_id": str(admin.id), "reason": "教师接回"}
    handover.confirm({**back, "revision": handover.preview(back)["revision"]})
    assert db.get(ScopedGrant, int(independent["id"])).status == "ACTIVE"
    assert db.get(ScopedGrant, int(result["grant_id"])).status == "REVOKED"
    assert [r["kind"] for r in permission_sources(db, reader.id, cid)] == ["EXPLICIT_GRANT"]
    from app.modules.identity.models import Role, UserRole

    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=reader.id, role_id=role.id))
    db.commit()
    service.create_grant(
        admin, cid, {"user_id": str(reader.id), "actions": ["volunteer.group.manage"]}
    )
    # A real teacher granted only cross-college group management cannot create
    # attendance correction / objection review privileges through handover.
    with pytest.raises(PermissionDeniedError):
        GroupHandoverService(db, reader, cid, gid).preview(body)
    from app.modules.academic.enrollment_models import TeacherCollegeBinding
    from app.modules.identity.models import UserAccount

    db.rollback()
    db.add(TeacherCollegeBinding(user_id=reader.id, college_id=cid))
    foreign = UserAccount(display_name="外院待授权账号", status="ACTIVE")
    db.add(foreign)
    db.commit()
    teacher_handover = GroupHandoverService(db, reader, cid, gid)
    # Full local teacher powers still cannot authorize an unrelated/foreign account.
    foreign_body = {"owner_user_id": str(foreign.id), "reason": "跨学院交接"}
    with pytest.raises(PermissionDeniedError):
        teacher_handover.preview(foreign_body)
    db.rollback()
    assert str(foreign.id) not in {u["id"] for u in teacher_handover.candidates()}
    assert teacher_handover.preview(body)["new_owner_user_id"] == str(reader.id)
    assert handover.preview(foreign_body)["new_owner_user_id"] == str(foreign.id)
