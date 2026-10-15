import pytest
from app.modules.academic.models import VolunteerQualification
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import AssignmentSetRequest
from app.modules.inspection.scoped_service import ScopedInspectionService
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.models import VolunteerGroup

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


@pytest.mark.parametrize("operation", ["candidates", "manual", "auto"])
def test_warn_is_explained_but_requires_plan_confirmation(campus, monkeypatch, operation):
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    if operation != "candidates" and db.get_bind().dialect.name != "mysql":
        pytest.skip("write path requires dedicated MySQL anchors and second reader connection")
    campus[0].publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": db.get(
                VolunteerGroup, int(group["id"]), populate_existing=True
            ).lock_version,
            "course_type_ids": group["configuration"]["course_type_ids"],
            "default_effect": "WARN",
            "own_class_effect": "WARN",
            "daily_limit": 2,
            "weekly_limit": 5,
        },
    )
    volunteer = UserAccount(display_name="warning fixture", student_id=own.id, status="ACTIVE")
    role = Role(code="VOLUNTEER", name="volunteer")
    db.add_all([volunteer, role])
    db.flush()
    db.add(UserRole(user_id=volunteer.id, role_id=role.id))
    db.add(
        VolunteerQualification(
            semester_id=sem.id, student_id=own.id, college_id=int(a["id"]), enabled=True
        )
    )
    db.commit()
    GroupMemberService(db, admin, int(a["id"]), int(group["id"])).create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-01",
            "effective_to": "2027-01-31",
        }
    )
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "warning",
    }
    generated = sampling.generate(body, sampling.preview(body)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    service = ScopedInspectionService(db, admin, int(a["id"]))
    expected = {"SELF_CLASS_WARNING", "OWN_COURSE_WARNING"}
    if operation == "candidates":
        result = service.list_task_volunteer_candidates(task.id, actor=admin)
        assert result[0].eligible
        assert set(result[0].warning_codes) == expected
    else:
        from app.core.exceptions import ConflictError
        with pytest.raises(ConflictError):
            if operation == "manual":
                service.assign_manual(admin, task.id,
                    AssignmentSetRequest(volunteer_user_id=volunteer.id, lock_version=task.lock_version), None)
            else:
                sampling.assign({"semester_id": str(sem.id), "task_ids": [str(task.id)]})
