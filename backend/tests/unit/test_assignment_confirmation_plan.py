import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import VolunteerQualification
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.models import VolunteerGroup
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="prepared")
def prepared_fixture(monkeypatch):
    source = campus_fixture.__wrapped__()
    campus = next(source)
    try:
        db, actor, a, sem, group, own, *_ = arrange(campus, monkeypatch)
        campus[0].publish_group(
            actor,
            int(a["id"]),
            int(group["id"]),
            {
                "lock_version": db.get(VolunteerGroup, int(group["id"])).lock_version,
                "course_type_ids": group["configuration"]["course_type_ids"],
                "default_effect": "WARN",
                "own_class_effect": "WARN",
            },
        )
        user = UserAccount(display_name="plan volunteer", student_id=own.id, status="ACTIVE")
        role = Role(code="VOLUNTEER", name="volunteer")
        db.add_all([user, role])
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add(
            VolunteerQualification(
                student_id=own.id, semester_id=sem.id, college_id=int(a["id"]), enabled=True
            )
        )
        db.commit()
        GroupMemberService(db, actor, int(a["id"]), int(group["id"])).create(
            {
                "student_id": str(own.id),
                "semester_id": str(sem.id),
                "effective_from": "2026-09-01",
                "effective_to": "2027-01-31",
            }
        )
        sampler = GroupSamplingService(db, actor, int(a["id"]), int(group["id"]))
        body = {
            "semester_id": str(sem.id),
            "date_from": "2026-09-07",
            "date_to": "2026-09-07",
            "counts": {str(own.administrative_class_id): 1},
            "draw_id": "confirmation",
        }
        result = sampler.generate(body, sampler.preview(body)["selection_revision"])
        from app.modules.inspection.assignment_plan_service import AssignmentPlanService
        from app.modules.inspection.scoped_service import ScopedInspectionService

        monkeypatch.setattr(ScopedInspectionService, "_lock_day_anchors", lambda *args: None)
        service = AssignmentPlanService(db, actor, int(a["id"]), int(group["id"]))
        yield db, service, sem, result.assignable_task_ids, user
    finally:
        source.close()


def test_warn_requires_specific_confirmation_and_commit_is_idempotent(prepared):
    db, service, sem, tasks, _ = prepared
    preview = service.preview({"semester_id": str(sem.id), "task_ids": tasks})
    assert preview["assigned"][0]["warning_codes"]
    with pytest.raises(ConflictError):
        service.commit(preview["id"], {"revision": preview["revision"], "confirmations": []})
    assert db.scalar(select(InspectionAssignment)) is None
    body = {"revision": preview["revision"], "confirmations": preview["assigned"]}
    result = service.commit(preview["id"], body)
    assert result["assigned_count"] == 1
    assert service.commit(preview["id"], body) == result
    assert len(list(db.scalars(select(InspectionAssignment)))) == 1


@pytest.mark.parametrize("change", ["task", "course"])
def test_plan_rejects_task_changed_after_preview(prepared, change):
    db, service, sem, tasks, _ = prepared
    preview = service.preview({"semester_id": str(sem.id), "task_ids": tasks})
    task = db.get(InspectionTask, int(tasks[0]))
    if change == "task":
        task.lock_version += 1
    else:
        from app.modules.academic.models import CourseSchedule

        db.get(CourseSchedule, task.course_schedule_id).start_period = 2
    db.commit()
    with pytest.raises(ConflictError):
        service.commit(
            preview["id"], {"revision": preview["revision"], "confirmations": preview["assigned"]}
        )
    assert db.scalar(select(InspectionAssignment)) is None
