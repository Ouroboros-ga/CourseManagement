import pytest
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture
def campus():
    yield from campus_fixture.__wrapped__()


def setup(campus):
    service, db, actor, _, a, b = campus
    cid = int(a["id"])
    live = service.create_type(actor, cid, {"name": "有效类型"})
    old = service.create_type(actor, cid, {"name": "已删除类型"})
    row = db.get(CourseType, int(old["id"]))
    row.status = "INACTIVE"
    row.deleted_at = utcnow()
    db.commit()
    group = service.create_group(actor, cid, {"name": "查课组", "owner_user_id": str(actor.id)})
    return service, db, actor, cid, group, live, old, b


def test_references_do_not_offer_deleted_types_as_conflict_rules(campus):
    service, _, actor, cid, group, live, old, _ = setup(campus)
    refs = service.group_references(actor, cid, int(group["id"]))
    assert old["id"] not in [r["id"] for r in refs["types"]]
    assert old["id"] not in [r["id"] for r in refs["conflict_types"]]
    assert live["id"] in [r["id"] for r in refs["conflict_types"]]


def test_stale_deleted_override_returns_actionable_conflict_instead_of_404(campus):
    service, _, actor, cid, group, live, old, _ = setup(campus)
    with pytest.raises(ConflictError, match="删除"):
        service.publish_group(
            actor,
            cid,
            int(group["id"]),
            {
                "lock_version": group["lock_version"],
                "course_type_ids": [live["id"]],
                "type_overrides": {old["id"]: "ALLOW"},
            },
        )


def test_foreign_type_still_returns_not_found(campus):
    service, _, actor, cid, group, live, _, other = setup(campus)
    foreign = service.create_type(actor, int(other["id"]), {"name": "外院类型"})
    with pytest.raises(NotFoundError):
        service.publish_group(
            actor,
            cid,
            int(group["id"]),
            {
                "lock_version": group["lock_version"],
                "course_type_ids": [live["id"]],
                "type_overrides": {foreign["id"]: "ALLOW"},
            },
        )
