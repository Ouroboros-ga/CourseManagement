from datetime import date

import pytest
from app.modules.volunteer.member_models import VolunteerGroupMember
from app.modules.volunteer.overview import semester_overview

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_rules import prepared_task


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_overview_counts_distinct_active_members_at_date_and_keeps_rules(campus):
    db, task, student, _, _, _ = prepared_task(campus)
    admin = campus[2]
    db.add(
        VolunteerGroupMember(
            college_id=task.college_id,
            group_id=task.group_id,
            semester_id=task.semester_id,
            student_id=student.id,
            effective_from=date(2026, 9, 8),
            effective_to=date(2026, 9, 12),
            status="ACTIVE",
        )
    )
    db.commit()
    result = semester_overview(db, admin, task.college_id, task.semester_id, date(2026, 9, 9))
    item = result["items"][str(task.group_id)]
    assert item["member_count"] == 1
    assert item["configuration"]["course_type_ids"]
    assert item["specific"] is False and item["error"] == ""
    assert "members" not in item
    ended = semester_overview(db, admin, task.college_id, task.semester_id, date(2026, 9, 14))
    assert ended["items"][str(task.group_id)]["member_count"] == 0


def test_overview_preserves_frozen_semester_config_and_group_grants(campus):
    from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup
    from app.modules.volunteer.preparation_models import GroupSemesterPreparation
    from sqlalchemy import select

    db, task, _, _, _, _ = prepared_task(campus)
    config, _, admin, teacher, college, _ = campus
    group = db.get(VolunteerGroup, task.group_id)
    old = db.scalar(
        select(GroupConfigVersion).where(GroupConfigVersion.id == task.group_config_version_id)
    )
    db.add(
        GroupSemesterPreparation(
            college_id=task.college_id,
            group_id=group.id,
            semester_id=task.semester_id,
            source_semester_id=task.semester_id,
            config_id=old.id,
        )
    )
    db.add(
        GroupConfigVersion(
            college_id=task.college_id,
            group_id=group.id,
            version=2,
            configuration={**old.configuration, "default_effect": "ALLOW"},
            published_by=admin.id,
        )
    )
    group.config_version = 2
    db.commit()
    body = {
        "user_id": str(teacher.id),
        "actions": ["volunteer.group.read"],
        "resource_scope": {"kind": "GROUPS", "ids": [str(group.id)]},
    }
    preview = config.preview_grant(admin, int(college["id"]), body)
    config.create_grant(
        admin, int(college["id"]), {**body, "preview_revision": preview["revision"]}
    )
    result = semester_overview(db, teacher, task.college_id, task.semester_id, date(2026, 9, 9))
    assert set(result["items"]) == {str(group.id)}
    item = result["items"][str(group.id)]
    assert item["specific"] is True
    assert item["configuration"] == old.configuration
