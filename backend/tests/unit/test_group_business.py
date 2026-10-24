import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, own, foreign = records(db, a, b)
    semester = db.get(Semester, teaching.semester_id)
    group = config.create_group(
        admin, int(a["id"]), {"name": "Morning", "owner_user_id": str(admin.id)}
    )
    another = config.create_group(
        admin, int(a["id"]), {"name": "Regular", "owner_user_id": str(admin.id)}
    )
    return config, db, admin, a, b, semester, group, another, own, foreign


def test_multi_group_membership_and_same_group_overlap(campus):
    from app.modules.volunteer.member_service import GroupMemberService

    _, db, admin, a, _, semester, one, two, own, _ = prepare(campus)
    service = GroupMemberService(db, admin, int(a["id"]), int(one["id"]))
    body = {
        "student_id": str(own.id),
        "semester_id": str(semester.id),
        "effective_from": "2026-09-07",
        "effective_to": "2027-01-31",
    }
    first = service.create(body)
    assert first["student_id"] == str(own.id)
    with pytest.raises(ConflictError):
        service.create(body)
    assert GroupMemberService(db, admin, int(a["id"]), int(two["id"])).create(body)
    assert len(service.members(semester.id)) == 1


def test_cross_college_membership_is_rejected(campus):
    from app.modules.volunteer.member_service import GroupMemberService

    _, db, admin, a, _, semester, group, _, _, foreign = prepare(campus)
    service = GroupMemberService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "student_id": str(foreign.id),
        "semester_id": str(semester.id),
        "effective_from": "2026-09-07",
        "effective_to": "2027-01-31",
    }
    with pytest.raises(ConflictError):
        service.create(body)
    assert service.members(semester.id) == []


def test_revoke_member_requires_current_version(campus):
    from app.modules.volunteer.member_service import GroupMemberService

    _, db, admin, a, _, semester, group, _, own, _ = prepare(campus)
    service = GroupMemberService(db, admin, int(a["id"]), int(group["id"]))
    row = service.create(
        {
            "student_id": str(own.id),
            "semester_id": str(semester.id),
            "effective_from": "2026-09-07",
            "effective_to": "2027-01-31",
        }
    )
    with pytest.raises(ConflictError):
        service.revoke(int(row["id"]), row["lock_version"] + 1)
    assert service.revoke(int(row["id"]), row["lock_version"])["status"] == "INACTIVE"


def test_cross_college_batch_does_not_partially_add_local_members(campus):
    from app.modules.volunteer.member_batch import GroupMemberBatchService
    from app.modules.volunteer.member_service import GroupMemberService

    _, db, admin, a, _, semester, group, _, own, foreign = prepare(campus)
    cid, gid = int(a["id"]), int(group["id"])
    with pytest.raises(ConflictError):
        GroupMemberBatchService(db, admin, cid, gid).preview({
            "semester_id": str(semester.id), "student_nos": [own.student_no, foreign.student_no],
            "effective_from": "2026-09-07", "effective_to": "2027-01-31"})
    assert GroupMemberService(db, admin, cid, gid).members(semester.id) == []


def test_dynamic_teaching_type_is_college_owned_and_versioned(campus):
    from app.modules.academic.scoped_service import ScopedAcademicService

    config, db, admin, _, a, b = campus
    _, _, _, teaching, *_ = records(db, a, b)
    morning = config.create_type(admin, int(a["id"]), {"name": "自定义早查"})
    foreign = config.create_type(admin, int(b["id"]), {"name": "同名独立类型"})
    service = ScopedAcademicService(db, admin, int(a["id"]))
    row = service.set_course_type(teaching.id, int(morning["id"]), 1)
    assert row["course_type_id"] == morning["id"] and row["classification_revision"] == 2
    with pytest.raises(ConflictError):
        service.set_course_type(teaching.id, int(morning["id"]), 1)
    with pytest.raises(NotFoundError):
        service.set_course_type(teaching.id, int(foreign["id"]), 2)


def test_group_specific_classes_and_default_course_conflict_are_configurable(campus):
    config, db, admin, _, a, b = campus
    own_class, foreign_class, _, teaching, *_ = records(db, a, b)
    kind = config.create_type(admin, int(a["id"]), {"name": "早查"})
    group = config.create_group(
        admin, int(a["id"]), {"name": "Group", "owner_user_id": str(admin.id)}
    )
    data = {
        "lock_version": group["lock_version"],
        "course_type_ids": [kind["id"]],
        "class_mode": "SPECIFIC",
        "class_ids": [str(own_class.id)],
        "default_effect": "ALLOW",
    }
    result = config.publish_group(admin, int(a["id"]), int(group["id"]), data)
    assert result["configuration"]["class_mode"] == "SPECIFIC"
    assert result["configuration"]["default_effect"] == "ALLOW"
    assert result["configuration"]["teaching_class_overrides"] == {}
    with pytest.raises(NotFoundError):
        config.publish_group(
            admin,
            int(a["id"]),
            int(group["id"]),
            {**data, "lock_version": result["lock_version"], "class_ids": [str(foreign_class.id)]},
        )
