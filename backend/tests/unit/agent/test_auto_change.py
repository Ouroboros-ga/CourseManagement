import pytest
from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.modules.academic.models import AdministrativeClass, Student, VolunteerQualification
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.auto_change_service import AutoChangeService
from app.modules.inspection.automation_models import AutoChangeExecution
from app.modules.inspection.models import AssignmentChangeRequest, InspectionAssignment
from app.modules.volunteer.member_service import GroupMemberService
from sqlalchemy import select


@pytest.fixture(name="prepared")
def fixture(monkeypatch):
    from tests.unit.test_assignment_confirmation_plan import prepared_fixture

    source = prepared_fixture.__wrapped__(monkeypatch)
    value = next(source)
    monkeypatch.setattr(get_settings(), "agent_auto_change_enabled", True)
    try:
        yield value
    finally:
        source.close()


def arrange(prepared, *, replacement=True):
    db, plans, semester, tasks, original = prepared
    preview = plans.preview(
        {
            "semester_id": str(semester.id),
            "task_ids": tasks,
            "assignments": {str(t): str(original.id) for t in tasks},
        }
    )
    plans.commit(
        preview["id"], {"revision": preview["revision"], "confirmations": preview["assigned"]}
    )
    old = db.scalar(select(InspectionAssignment).where(InspectionAssignment.revoked_at.is_(None)))
    other = None
    if replacement:
        classroom = AdministrativeClass(
            class_code="AUTO-REPLACEMENT", class_name="Other class", college_id=plans.cid
        )
        db.add(classroom)
        db.flush()
        student = Student(
            student_no="AUTO-REPLACEMENT",
            name="Replacement",
            administrative_class_id=classroom.id,
            status="ACTIVE",
        )
        db.add(student)
        db.flush()
        other = UserAccount(display_name="Replacement", student_id=student.id, status="ACTIVE")
        db.add(other)
        db.flush()
        role = db.scalar(select(Role).where(Role.code == "VOLUNTEER"))
        db.add(UserRole(user_id=other.id, role_id=role.id))
        db.add(
            VolunteerQualification(
                student_id=student.id, semester_id=semester.id, college_id=plans.cid, enabled=True
            )
        )
        db.commit()
        GroupMemberService(db, plans.actor, plans.cid, plans.gid).create(
            {
                "student_id": str(student.id),
                "semester_id": str(semester.id),
                "effective_from": "2026-09-01",
                "effective_to": "2027-01-31",
            }
        )
    return db, AutoChangeService(db, plans.cid, plans.gid, semester.id), plans, old, other


def request(db, old):
    value = AssignmentChangeRequest(
        assignment_id=old.id,
        request_user_id=old.volunteer_user_id,
        reason="Not available",
        status="PENDING",
    )
    db.add(value)
    db.flush()
    return value


def test_auto_change_reassigns_and_preserves_system_provenance(prepared):
    db, auto, plans, old, other = arrange(prepared)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    req = request(db, old)
    execution = auto.register(req.id)
    db.commit()
    result = auto.prepare(execution.id)
    assert result["status"] == "PREPARED"
    result = auto.apply(execution.id)
    assert result["status"] == "SUCCEEDED"
    active = db.scalar(
        select(InspectionAssignment).where(InspectionAssignment.revoked_at.is_(None))
    )
    assert active.volunteer_user_id == other.id
    assert active.assigned_by is None and active.assign_method == "AUTO"
    assert db.get(InspectionAssignment, old.id).revoked_at is not None
    assert db.get(AssignmentChangeRequest, req.id).status == "APPROVED"
    assert db.get(AssignmentChangeRequest, req.id).processed_by is None
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "assignment.auto_change.apply"))
    assert audit.actor_user_id is None
    assert audit.after_json["automation"]["authorizer_user_id"] == str(plans.actor.id)
    assert auto.apply(execution.id) == result
    assert db.query(InspectionAssignment).count() == 2


def test_no_candidate_leaves_original_and_pending_request(prepared):
    db, auto, plans, old, _ = arrange(prepared, replacement=False)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    req = request(db, old)
    execution = auto.register(req.id)
    db.commit()
    assert auto.prepare(execution.id)["status"] == "MANUAL_REQUIRED"
    assert db.get(AssignmentChangeRequest, req.id).status == "PENDING"
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_disabled_policy_cannot_apply_prepared_change(prepared):
    db, auto, plans, old, _ = arrange(prepared)
    policy = auto.set_policy(plans.actor, enabled=True, current_version=0)
    execution = auto.register(request(db, old).id)
    db.commit()
    auto.prepare(execution.id)
    auto.set_policy(plans.actor, enabled=False, current_version=policy["version"])
    with pytest.raises(ConflictError):
        auto.apply(execution.id)
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_manual_commit_cannot_be_relabelled_as_system_execution(prepared):
    db, auto, plans, old, _ = arrange(prepared)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    req = request(db, old)
    execution = auto.register(req.id)
    db.commit()
    preview = auto.prepare(execution.id)
    plans.commit(preview["plan_id"], {"revision": preview["revision"], "confirmations": []})
    with pytest.raises(ConflictError):
        auto.apply(execution.id)
    assert db.get(AutoChangeExecution, execution.id).status == "PREPARED"
    assert db.get(AssignmentChangeRequest, req.id).processed_by == plans.actor.id
    assert db.query(InspectionAssignment).count() == 2


def test_enabling_does_not_process_existing_requests(prepared):
    db, auto, plans, old, _ = arrange(prepared)
    existing = request(db, old)
    db.commit()
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    assert auto.register(existing.id) is None
    assert db.query(AutoChangeExecution).count() == 0


def test_receipt_failure_rolls_back_actual_reassignment(prepared, monkeypatch):
    db, auto, plans, old, _ = arrange(prepared)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    req = request(db, old)
    execution = auto.register(req.id)
    db.commit()
    auto.prepare(execution.id)

    def fail(*_):
        raise RuntimeError("receipt write failed")

    monkeypatch.setattr(auto, "_record_success", fail)
    with pytest.raises(RuntimeError, match="receipt"):
        auto.apply(execution.id)
    assert db.get(InspectionAssignment, old.id).revoked_at is None
    assert db.get(AssignmentChangeRequest, req.id).status == "PENDING"
    assert db.query(InspectionAssignment).count() == 1


@pytest.mark.parametrize("registration_fails", [False, True])
def test_real_volunteer_request_registers_policy_execution(
    prepared, monkeypatch, registration_fails
):
    from app.modules.identity.models import Permission, RolePermission
    from app.modules.identity.service import CurrentUser
    from app.modules.inspection.schemas import ChangeRequestCreateRequest
    from app.modules.inspection.service import InspectionService

    db, auto, plans, old, _ = arrange(prepared)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    role = db.scalar(select(Role).where(Role.code == "VOLUNTEER"))
    permission = Permission(code="assignment.change_request", name="Change request")
    db.add(permission)
    db.flush()
    db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()
    user = db.get(UserAccount, old.volunteer_user_id)
    actor = CurrentUser(user.id, user.username, user.display_name, user.status, ["VOLUNTEER"], [])
    if registration_fails:
        original_register = AutoChangeService.register

        def fail_after_registration(self, request_id):
            original_register(self, request_id)
            raise RuntimeError("event registration failed")

        monkeypatch.setattr(AutoChangeService, "register", fail_after_registration)
        with pytest.raises(RuntimeError, match="registration"):
            InspectionService(db).create_change_request(
                actor, ChangeRequestCreateRequest(assignment_id=old.id), None
            )
        assert db.query(AssignmentChangeRequest).count() == 0
        assert db.query(AutoChangeExecution).count() == 0
        return
    response = InspectionService(db).create_change_request(
        actor, ChangeRequestCreateRequest(assignment_id=old.id), None
    )
    execution = db.scalar(
        select(AutoChangeExecution).where(AutoChangeExecution.request_id == int(response.id))
    )
    assert execution is not None and execution.status == "QUEUED"
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_auto_change_migration_keeps_policy_history(prepared):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a003_auto_change.py"
    spec = importlib.util.spec_from_file_location("auto_change_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db, _, _, _, _ = prepared
    db.commit()
    with db.bind.begin() as connection:
        connection.execute(text("DROP TABLE auto_change_execution"))
        connection.execute(text("DROP TABLE auto_change_policy"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {"auto_change_execution", "auto_change_policy"} <= set(
                inspect(connection).get_table_names()
            )

            migration.downgrade()
            migration.upgrade()
    db.expire_all()
    db, auto, plans, _, _ = arrange(prepared)
    auto.set_policy(plans.actor, enabled=True, current_version=0)
    db.commit()
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        with pytest.raises(RuntimeError, match="auto_change_policy"):
            migration.downgrade()
        assert {"auto_change_execution", "auto_change_policy"} <= set(
            inspect(connection).get_table_names()
        )


def test_policy_api_scope_version_validation_and_switch(prepared, monkeypatch):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import CurrentUser
    from fastapi.testclient import TestClient

    db, plans, semester, _, user = prepared
    monkeypatch.setattr(get_settings(), "campus_configuration_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_academic_scoped_enabled", True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: plans.actor
    client = TestClient(app)
    path = f"/api/v1/colleges/{plans.cid}/groups/{plans.gid}/inspection/auto-change-policy"
    response = client.get(path, params={"semester_id": str(semester.id)})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["enabled"] is False
    body = {"semester_id": str(semester.id), "enabled": True, "current_version": 0}
    assert client.put(path, json={**body, "authorizer_user_id": "1"}).status_code == 422
    assert client.put(path, json={**body, "enabled": "false"}).status_code == 422
    response = client.put(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["authorizer_user_id"] == str(plans.actor.id)
    assert client.put(path, json=body).status_code == 409
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user.id, user.username, user.display_name, user.status, ["VOLUNTEER"], []
    )
    assert client.get(path, params={"semester_id": str(semester.id)}).status_code in (403, 404)
    assert client.put(path, json={**body, "current_version": 1}).status_code in (403, 404)
    app.dependency_overrides[get_current_user] = lambda: plans.actor
    monkeypatch.setattr(get_settings(), "agent_auto_change_enabled", False)
    assert client.get(path, params={"semester_id": str(semester.id)}).status_code == 404
