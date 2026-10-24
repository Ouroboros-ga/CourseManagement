import pytest
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, RolePermission, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from sqlalchemy import select
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result


@pytest.fixture(name="case")
def fixture(monkeypatch):
    yield from case_fixture.__wrapped__(monkeypatch)


def owner(case):
    db, _, _, _, objection, _ = case
    user = UserAccount(display_name="合成学生", status="ACTIVE", student_id=objection.student_id)
    role = Role(code="STUDENT", name="学生")
    permission = Permission(code="objection.read", name="读取本人申诉")
    db.add_all([user, role, permission])
    db.flush()
    db.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            RolePermission(role_id=role.id, permission_id=permission.id),
        ]
    )
    db.commit()
    return CurrentUser(user.id, None, "合成学生", "ACTIVE", ["STUDENT"], ["objection.read"])


def progress(case, actor=None, oid=None):
    from app.modules.objection.student_progress import StudentObjectionProgressService

    db, _, _, _, objection, _ = case
    return StudentObjectionProgressService(db).get(actor or owner(case), oid or objection.id)


def test_owner_reads_submitted_progress_without_creating_a_job(case):
    actor = owner(case)
    db = case[0]
    before = len(db.scalars(select(AuditLog)).all())
    value = progress(case, actor)
    assert value.stage == "SUBMITTED" and value.final_status == "PENDING"
    assert value.objection_id == str(case[4].id)
    assert db.scalars(select(ObjectionPrecheckJob)).all() == []
    assert len(db.scalars(select(AuditLog)).all()) == before


@pytest.mark.parametrize(
    "status,stage",
    [
        ("QUEUED", "PRECHECK_QUEUED"),
        ("RUNNING", "PRECHECK_RUNNING"),
        ("FAILED", "ACADEMIC_REVIEW"),
        ("STALE", "ACADEMIC_REVIEW"),
    ],
)
def test_public_stage_does_not_publish_internal_failure_details(case, status, stage):
    _, job = queue(case)
    job.status = status
    job.attempt_token = "private-attempt"
    job.error_code = "PRIVATE_INTERNAL_ERROR"
    case[0].commit()
    value = progress(case)
    assert value.stage == stage
    assert set(value.model_dump()) == {
        "objection_id",
        "stage",
        "label",
        "description",
        "final_status",
        "updated_at",
    }
    assert "private" not in value.model_dump_json().lower()


def test_successful_precheck_is_waiting_for_human_and_advice_is_not_published(case):
    service, job = queue(case)
    service.finish(job.id, service.begin(job.id), result())
    value = progress(case)
    assert value.stage == "ACADEMIC_REVIEW" and value.final_status == "PENDING"
    assert result().summary not in value.model_dump_json()


def test_changed_attendance_does_not_show_obsolete_running_progress(case):
    _, job = queue(case)
    job.status = "RUNNING"
    record = case[0].get(AttendanceRecord, case[4].attendance_record_id)
    record.current_version += 1
    case[0].commit()
    assert progress(case).stage == "ACADEMIC_REVIEW"
    assert job.status == "RUNNING"  # GET must not mutate execution or cloud tracking.


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
def test_formal_review_wins_over_old_precheck_state(case, status):
    queue(case)
    case[4].final_status = status
    case[0].commit()
    value = progress(case)
    assert value.stage == "COMPLETED" and value.final_status == status


def test_withdrawn_record_has_a_readable_history_status(case):
    queue(case)
    record = case[0].get(AttendanceRecord, case[4].attendance_record_id)
    record.effect_state = "WITHDRAWN"
    case[0].commit()
    assert progress(case).stage == "RECORD_WITHDRAWN"


def test_other_student_and_nonexistent_cases_share_not_found(case):
    actor = owner(case)
    for oid in [case[5].id, 2**63 - 1]:
        with pytest.raises(NotFoundError):
            progress(case, actor, oid)


def test_actual_binding_and_permission_are_rechecked(case):
    actor = owner(case)
    db = case[0]
    user = db.get(UserAccount, actor.id)
    user.student_id = None
    db.commit()
    with pytest.raises(NotFoundError):
        progress(case, actor)
    user.student_id = case[4].student_id
    db.query(RolePermission).filter(
        RolePermission.role_id == db.scalar(select(Role.id).where(Role.code == "STUDENT"))
    ).delete()
    db.commit()
    with pytest.raises(PermissionDeniedError):
        progress(case, actor)


def test_disabled_feature_does_not_read_or_create_precheck_tasks(case, monkeypatch):
    actor = owner(case)
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
    with pytest.raises(NotFoundError):
        progress(case, actor)


def test_archived_semester_is_readable_but_not_presented_as_active_processing(case):
    from app.modules.academic.models import Semester
    from app.modules.inspection.models import InspectionTask

    db, _, _, _, objection, _ = case
    task_id = db.get(AttendanceRecord, objection.attendance_record_id).task_id
    semester_id = db.get(InspectionTask, task_id).semester_id
    db.get(Semester, semester_id).status = "ARCHIVED"
    db.commit()
    assert progress(case).stage == "ARCHIVED"


def test_disabled_account_does_not_reuse_cached_student_identity(case):
    actor = owner(case)
    case[0].get(UserAccount, actor.id).status = "DISABLED"
    case[0].commit()
    with pytest.raises(PermissionDeniedError):
        progress(case, actor)


def test_personal_http_endpoint_uses_owner_and_bounds_ids(case, monkeypatch):
    from app.core import database
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    actor = owner(case)
    factory = sessionmaker(bind=case[0].bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    client = TestClient(app)
    path = f"/api/v1/me/objections/{case[4].id}/progress"
    assert client.get(path).status_code == 200
    schema = app.openapi()
    fields = schema["components"]["schemas"]["StudentObjectionProgress"]["properties"]
    assert set(fields) == {
        "objection_id", "stage", "label", "description", "final_status", "updated_at"
    }
    other = f"/api/v1/me/objections/{case[5].id}/progress"
    assert client.get(other + f"?student_id={case[5].student_id}").status_code == 404
    assert client.get("/api/v1/me/objections/9223372036854775808/progress").status_code == 422
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
    assert client.get(path).status_code == 404
    app.dependency_overrides.clear()
    assert client.get(path, headers={"X-Agent-Run-Token": "synthetic"}).status_code == 401


def test_policy_disabled_no_longer_advertises_queued_work_as_automatic_processing(case):
    service, _ = queue(case)
    service.set_policy(case[1], enabled=False, current_version=1)
    assert progress(case).stage == "ACADEMIC_REVIEW"


def test_other_environment_is_not_presented_as_current_student_progress(case):
    _, job = queue(case)
    job.environment = "unrelated-environment"
    case[0].commit()
    assert progress(case).stage == "SUBMITTED"


def test_same_college_does_not_make_another_student_visible(case):
    from app.modules.inspection.models import InspectionTask

    db, _, cid, _, _, foreign = case
    actor = owner(case)
    task_id = db.get(AttendanceRecord, foreign.attendance_record_id).task_id
    db.get(InspectionTask, task_id).college_id = cid
    db.commit()
    with pytest.raises(NotFoundError):
        progress(case, actor, foreign.id)
