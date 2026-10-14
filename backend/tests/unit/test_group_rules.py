from datetime import date

import pytest
from app.core.exceptions import ConflictError
from app.modules.inspection.models import InspectionTask

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_business import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def prepared_task(campus):
    from app.modules.volunteer.member_service import GroupMemberService
    from app.modules.volunteer.models import GroupConfigVersion
    from sqlalchemy import select

    config, db, admin, a, b, sem, group, _, own, foreign = prepare(campus)
    kind = config.create_type(admin, int(a["id"]), {"name": "可编辑早查"})
    published = config.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": group["lock_version"],
            "course_type_ids": [kind["id"]],
            "type_overrides": {kind["id"]: "ALLOW"},
            "teaching_class_overrides": {"1": "BLOCK"},
        },
    )
    config.update_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"status": "ACTIVE", "lock_version": published["lock_version"]},
    )
    version = db.scalar(
        select(GroupConfigVersion).where(GroupConfigVersion.group_id == int(group["id"]))
    )
    member_service = GroupMemberService(db, admin, int(a["id"]), int(group["id"]))
    member_service.create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-07",
            "effective_to": "2026-09-14",
        }
    )
    task = InspectionTask(
        task_key="GROUP",
        semester_id=sem.id,
        college_id=int(a["id"]),
        inspection_date=date(2026, 9, 7),
        week_no=2,
        inspection_type="COURSE",
        start_period=1,
        end_period=1,
        group_id=int(group["id"]),
        group_config_version_id=version.id,
        course_type_id_snapshot=int(kind["id"]),
    )
    return db, task, own, foreign, member_service, kind


def test_membership_is_date_scoped_and_group_course_exception_has_priority(campus):
    from app.modules.volunteer.rules import GroupRules

    db, task, own, foreign, _, kind = prepared_task(campus)
    rules = GroupRules(db, task)
    assert rules.member_allowed(own.id)
    assert not rules.member_allowed(foreign.id)
    assert rules.course_effect(2, int(kind["id"])) == "ALLOW"
    assert rules.course_effect(1, int(kind["id"])) == "BLOCK"
    assert rules.course_effect(2, None) == "BLOCK"
    task.inspection_date = date(2026, 9, 14)
    assert not GroupRules(db, task).member_allowed(own.id)


def test_out_of_group_type_cannot_be_assigned(campus):
    from app.modules.volunteer.rules import GroupRules

    db, task, own, _, _, _ = prepared_task(campus)
    task.course_type_id_snapshot = 999
    with pytest.raises(ConflictError):
        GroupRules(db, task)
