from hashlib import sha256

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.run_context import AppConnection, RunService
from app.modules.identity.models import Permission, RolePermission, UserAccount
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select
from tests.unit.agent.test_run_context import connection, session_for
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_summary_uses_current_college_and_rejects_revoked_binding(campus, monkeypatch):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    auth = session_for(db, actor)
    app = AppConnection(
        app_key_id="management",
        entry_kind="MANAGEMENT",
        environment="dev",
        key_digest=sha256(("m" * 40).encode()).hexdigest(),
    )
    service = RunService(db, [app], environment="dev")
    _, token = service.issue("management", actor.id, auth.id, college_id=int(campus[4]["id"]))
    task = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[4]["id"]))
    )
    args = {"semester_id": str(task.semester_id), "week_no": task.week_no}
    result = invoke_tool(db, service.resolve("m" * 40, token), "report_attendance_summary", args)
    assert result.data["eligible_task_count"] == 1
    assert set(result.data) == {"overall", "eligible_task_count"}
    db.delete(db.get(TeacherCollegeBinding, actor.id))
    db.commit()
    with pytest.raises(AppError):
        invoke_tool(db, service.resolve("m" * 40, token), "report_attendance_summary", args)


def test_self_attendance_cannot_expand_to_other_student(campus, monkeypatch):
    from app.modules.identity.models import Role
    from tests.unit.test_scoped_attendance import prepare

    db, _, _, _, own, foreign = prepare(campus)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    user = UserAccount(display_name="Student", student_id=own.student_id, status="ACTIVE")
    db.add(user)
    db.commit()
    auth = session_for(db, user)
    role = db.scalar(select(Role).where(Role.code == "STUDENT"))
    permission = Permission(code="attendance.read", name="attendance")
    db.add(permission)
    db.flush()
    db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()
    service = RunService(db, [connection()], environment="dev")
    _, token = service.issue("self-app", user.id, auth.id)
    context = service.resolve("a" * 40, token)
    result = invoke_tool(db, context, "self_attendance_list", {})
    assert result.data["total"] == 1
    assert result.data["items"][0]["id"] == str(own.id)
    assert str(foreign.id) not in [item["id"] for item in result.data["items"]]
    # Even a valid foreign task filter can only narrow the student's own records.
    result = invoke_tool(db, context, "self_attendance_list", {"task_id": str(foreign.task_id)})
    assert result.data["total"] == 0


def test_timetable_read_does_not_initialize_a_missing_copy(campus):
    from app.modules.timetable.models import PersonalTimetable
    from tests.unit.test_scoped_attendance import prepare

    db, _, _, _, own, _ = prepare(campus)
    user = UserAccount(display_name="Student", student_id=own.student_id, status="ACTIVE")
    db.add(user)
    db.commit()
    auth = session_for(db, user)
    service = RunService(db, [connection()], environment="dev")
    _, token = service.issue("self-app", user.id, auth.id)
    task = db.get(InspectionTask, own.task_id)
    result = invoke_tool(
        db,
        service.resolve("a" * 40, token),
        "self_timetable_get",
        {"semester_id": str(task.semester_id)},
    )
    assert result.data["status"] == "NOT_INITIALIZED"
    assert db.scalar(select(PersonalTimetable.id)) is None


def test_responsibility_tool_obeys_revoked_college_action(campus, monkeypatch):
    from tests.unit.test_campus_configuration import grant
    from tests.unit.test_scoped_attendance import prepare

    db, actor, a, _, own, _ = prepare(campus)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    authorization = grant(campus[0], campus[2], actor, a, ["inspection.read"])
    auth = session_for(db, actor)
    app = AppConnection(
        app_key_id="management",
        entry_kind="MANAGEMENT",
        environment="dev",
        key_digest=sha256(("m" * 40).encode()).hexdigest(),
    )
    service = RunService(db, [app], environment="dev")
    _, token = service.issue("management", actor.id, auth.id, college_id=int(a["id"]))
    task = db.get(InspectionTask, own.task_id)
    args = {"semester_id": str(task.semester_id), "week_no": task.week_no}
    result = invoke_tool(db, service.resolve("m" * 40, token), "responsibility_tasks_list", args)
    assert result.data["total"] == 1
    assert result.data["items"][0]["id"] == str(task.id)
    campus[0].revoke_grant(
        campus[2], int(a["id"]), authorization["id"], authorization["lock_version"]
    )
    with pytest.raises(AppError):
        invoke_tool(db, service.resolve("m" * 40, token), "responsibility_tasks_list", args)


def test_group_limited_run_never_becomes_college_wide(campus, monkeypatch):
    from app.modules.inspection.group_sampling import GroupSamplingService
    from tests.unit.test_group_sampling_business import arrange

    db, admin, college, semester, group, own, *_ = arrange(campus, monkeypatch)
    config, _, _, responsible, *_ = campus
    grant = {
        "user_id": str(responsible.id),
        "actions": ["inspection.read"],
        "resource_scope": {"kind": "GROUPS", "ids": [group["id"]]},
    }
    grant["preview_revision"] = config.preview_grant(admin, int(college["id"]), grant)["revision"]
    config.create_grant(admin, int(college["id"]), grant)
    sampler = GroupSamplingService(db, admin, int(college["id"]), int(group["id"]))
    body = {
        "semester_id": str(semester.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "agent-scope",
    }
    generated = sampler.generate(body, sampler.preview(body)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    auth = session_for(db, responsible)
    app = AppConnection(
        app_key_id="management",
        entry_kind="MANAGEMENT",
        environment="dev",
        key_digest=sha256(("m" * 40).encode()).hexdigest(),
    )
    service = RunService(db, [app], environment="dev")
    _, token = service.issue("management", responsible.id, auth.id, college_id=int(college["id"]))
    context = service.resolve("m" * 40, token)
    result = invoke_tool(
        db,
        context,
        "responsibility_tasks_list",
        {"semester_id": str(semester.id), "week_no": task.week_no},
    )
    assert result.data["total"] == 1
    assert result.data["items"][0]["id"] == str(task.id)
    with pytest.raises(AppError):
        invoke_tool(
            db,
            context,
            "report_attendance_summary",
            {"semester_id": str(semester.id), "week_no": task.week_no},
        )
