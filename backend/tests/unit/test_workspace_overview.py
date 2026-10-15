"""工作台按真实动作范围聚合；无权的项不返回零值假装可见。"""

import pytest

from tests.unit.test_campus_configuration import campus as campus_fixture, grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def overview(db, actor, cid, sid):
    from app.modules.organization.overview import WorkspaceOverviewService
    return WorkspaceOverviewService(db, actor, int(cid)).read(sid)


def test_overview_excludes_foreign_students_and_unpermitted_sections(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    grant(config, admin, teacher, a, ["student.read"])
    result = overview(db, teacher, a["id"], teaching.semester_id)
    items = {item["id"]: item for item in result["items"]}
    assert items["students"]["count"] == 1
    assert "schedules" not in items and "objections" not in items and "members" not in items
    assert result["college_id"] == a["id"]
    assert result["semester_id"] == str(teaching.semester_id)


def test_overview_tracks_real_academic_counts_and_missing_classification(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    grant(config, admin, teacher, a, ["academic.read"])
    result = overview(db, teacher, a["id"], teaching.semester_id)
    items = {item["id"]: item for item in result["items"]}
    assert items["schedules"]["count"] == 1
    assert items["unclassified"]["count"] == 1
    assert items["unclassified"]["status"] == "ACTION_REQUIRED"
    assert "students" not in items and "qualifications" not in items


def test_overview_rechecks_revoked_access(campus):
    from app.core.exceptions import NotFoundError
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    with pytest.raises(NotFoundError):
        overview(db, teacher, a["id"], teaching.semester_id)


def test_group_limited_overview_cannot_count_other_groups(campus):
    from app.modules.organization.models import ScopedGrant
    from app.modules.volunteer.models import VolunteerGroup
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    one = VolunteerGroup(college_id=int(a["id"]), name="Visible", normalized_name="visible",
                         owner_user_id=admin.id, status="ACTIVE")
    other = VolunteerGroup(college_id=int(a["id"]), name="Hidden", normalized_name="hidden",
                           owner_user_id=admin.id, status="ACTIVE")
    db.add_all([one, other]); db.flush()
    db.add(ScopedGrant(college_id=int(a["id"]), user_id=teacher.id, granted_by=admin.id,
                       actions=["volunteer.group.read"],
                       resource_scope={"kind": "GROUPS", "ids": [str(one.id)]}))
    db.commit()
    items = {item["id"]: item for item in overview(db, teacher, a["id"], teaching.semester_id)["items"]}
    assert items["groups"]["count"] == 1
    assert set(items) == {"groups", "members"}
