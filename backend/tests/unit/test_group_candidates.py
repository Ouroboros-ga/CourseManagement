import pytest
from app.modules.academic.models import Student, VolunteerQualification
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.scoped_service import ScopedInspectionService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_legacy_foreign_member_never_appears_as_candidate(campus, monkeypatch):
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    foreign = db.scalar(select(Student).where(Student.student_no == "B"))
    person = UserAccount(display_name="support", student_id=foreign.id, status="ACTIVE")
    role = Role(code="VOLUNTEER", name="volunteer")
    db.add_all([person, role])
    db.flush()
    db.add(UserRole(user_id=person.id, role_id=role.id))
    db.add(
        VolunteerQualification(
            student_id=foreign.id, semester_id=sem.id, college_id=int(campus[5]["id"]), enabled=True
        )
    )
    db.commit()
    from datetime import date

    from app.modules.volunteer.member_models import VolunteerGroupMember, VolunteerGroupSupport

    fields = dict(
        college_id=int(a["id"]),
        group_id=int(group["id"]),
        student_id=foreign.id,
        semester_id=sem.id,
        effective_from=date(2026, 9, 1),
        effective_to=date(2027, 1, 31),
    )
    support = VolunteerGroupSupport(
        **fields,
        authorized_by=admin.id,
        scope_snapshot={
            "course_type_ids": group["configuration"]["course_type_ids"],
            "class_mode": "ALL_AUTHORIZED",
        },
    )
    db.add_all([support, VolunteerGroupMember(**fields)])
    db.commit()
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "support",
    }
    sampling.generate(body, sampling.preview(body)["selection_revision"])
    task = db.scalar(select(InspectionTask).where(InspectionTask.group_id == int(group["id"])))
    service = ScopedInspectionService(db, admin, int(a["id"]))
    candidates = service.list_task_volunteer_candidates(task.id, actor=admin)
    assert candidates == []
    db.rollback()
    support.status = "INACTIVE"
    db.commit()
    assert service.list_task_volunteer_candidates(task.id, actor=admin) == []
