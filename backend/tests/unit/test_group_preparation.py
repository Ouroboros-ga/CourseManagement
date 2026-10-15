from datetime import date

import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import Semester, Student, VolunteerQualification
from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.models import VolunteerGroup
from app.modules.volunteer.preparation import GroupPreparationService
from app.modules.volunteer.preparation_models import semester_group_config
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_preparation_reuses_identity_rechecks_qualification_and_selects_semester_rules(
    campus, monkeypatch
):
    db, admin, a, source, group, student, *_ = arrange(campus, monkeypatch)
    cid, gid = int(a["id"]), int(group["id"])
    member = GroupMemberService(db, admin, cid, gid).create(
        {
            "student_id": str(student.id),
            "semester_id": str(source.id),
            "effective_from": source.start_date,
            "effective_to": source.end_date,
        }
    )
    target = Semester(
        code="2027-B",
        name="新学期",
        start_date=date(2027, 3, 1),
        end_date=date(2027, 7, 1),
        first_monday=date(2027, 3, 1),
        total_weeks=18,
    )
    db.add(target)
    db.commit()
    identity_count = db.scalar(select(func.count()).select_from(Student))
    service = GroupPreparationService(db, admin, cid, gid, target.id)
    body = {
        "source_semester_id": str(source.id),
        "member_ids": [member["id"]],
        "effective_from": target.start_date,
        "effective_to": target.end_date,
    }
    not_ready = service.preview(body)
    assert not not_ready["can_confirm"]
    with pytest.raises(ConflictError):
        service.confirm({**body, "revision": not_ready["revision"]})
    db.add(
        VolunteerQualification(
            student_id=student.id, semester_id=target.id, college_id=cid, enabled=True
        )
    )
    db.commit()
    preview = service.preview(body)
    assert preview["can_confirm"] and not preview["support_grants_copied"]
    result = service.confirm({**body, "revision": preview["revision"]})
    assert result["created_members"] == 1 and result["group_id"] == str(gid)
    actual = db.get(VolunteerGroup, gid)
    assert semester_group_config(db, actual, target.id).id == int(result["config_id"])
    assert semester_group_config(db, actual, source.id).id != int(result["config_id"])
    assert db.scalar(select(func.count()).select_from(Student)) == identity_count
    assert db.scalar(select(func.count()).select_from(VolunteerGroupSupport)) == 0
    assert (
        len(
            list(
                db.scalars(select(VolunteerGroupMember).where(VolunteerGroupMember.group_id == gid))
            )
        )
        == 2
    )
