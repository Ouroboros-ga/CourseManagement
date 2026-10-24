from datetime import datetime, timedelta

import pytest
from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.core.security import create_access_token
from app.main import create_app
from app.modules.identity.models import UserAccount
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.unit.agent import test_weekly_inspection as weekly_tests
from tests.unit.agent.test_run_context import session_for
from tests.unit.agent.test_weekly_inspection import arrange


@pytest.fixture(name="case")
def fixture(monkeypatch):
    source = weekly_tests.fixture.__wrapped__(monkeypatch)
    value = next(source)
    db, actor, cid, semester, gid, *_ = value
    auth = session_for(db, db.get(UserAccount, actor.id))
    token = create_access_token(
        user_id=actor.id, session_id=auth.id, roles=["SUPER_ADMIN"], permissions=["*"],
    )
    app = create_app()

    def database():
        yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    client.params = {"semester_id": str(semester.id)}
    root = f"/api/v1/colleges/{cid}/groups/{gid}/inspection/weekly"
    try:
        yield value, client, root, auth, monkeypatch
    finally:
        client.close()
        source.close()


def save(case):
    _, body = arrange(case[0])
    response = case[1].put(f"{case[2]}/policy", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def due(case):
    import app.modules.inspection.weekly_service as module

    case[4].setattr(module, "utcnow", lambda: datetime(2026, 9, 4, 8))
    response = case[1].post(f"{case[2]}/due", json={"current_version": 1})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_real_login_policy_due_history_pause_and_strict_optimistic_version(case):
    value, client, root, *_ = case
    response = client.get(f"{root}/policy")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["plan"] is None
    plan = save(case)
    assert plan["authorizer_user_id"] == str(value[1].id)
    run = due(case)[0]
    assert due(case) == []
    history = client.get(f"{root}/executions")
    assert history.status_code == 200, history.text
    assert history.headers["Cache-Control"] == "private, no-store"
    assert history.json()["data"]["items"][0]["id"] == run["id"]
    detail = client.get(f"{root}/executions/{run['id']}")
    assert detail.status_code == 200 and detail.json()["data"]["status"] == "QUEUED"
    paused = client.post(f"{root}/policy/pause", json={"current_version": 1})
    assert paused.status_code == 200 and paused.json()["data"]["enabled"] is False
    assert client.post(f"{root}/due", json={"current_version": 1}).status_code == 409
    assert client.post(f"{root}/policy/pause", json={"current_version": 1}).status_code == 409
    assert client.get(f"{root}/executions/{run['id']}").status_code == 200


def test_history_get_does_not_generate_or_rewrite_business_facts_after_group_inactivation(case):
    from app.modules.audit.models import AuditLog
    from app.modules.inspection.models import InspectionAssignment, InspectionTask
    from app.modules.inspection.weekly_models import WeeklyInspectionExecution
    from app.modules.volunteer.models import VolunteerGroup

    save(case)
    run = due(case)[0]
    db = case[0][0]
    db.get(VolunteerGroup, case[0][4]).status = "INACTIVE"
    case[0][3].status = "ARCHIVED"
    db.commit()
    models = (InspectionTask, InspectionAssignment, AuditLog)
    counts = [db.query(model).count() for model in models]
    assert case[1].get(f"{case[2]}/policy").status_code == 200
    for _ in range(2):
        assert case[1].get(f"{case[2]}/executions/{run['id']}").status_code == 200
        assert case[1].get(f"{case[2]}/executions").status_code == 200
    assert [db.query(model).count() for model in models] == counts
    assert db.get(WeeklyInspectionExecution, int(run["id"])).status == "QUEUED"


def test_missing_revoked_login_and_forged_jwt_roles_do_not_grant_access(case):
    value, client, root, auth, _ = case
    assert client.get(f"{root}/policy", headers={"Authorization": ""}).status_code == 401
    other = value[0].scalar(select(UserAccount).where(UserAccount.id != value[1].id))
    other_session = session_for(value[0], other)
    forged = create_access_token(
        user_id=other.id, session_id=other_session.id, roles=["SUPER_ADMIN"], permissions=["*"],
    )
    denied = client.get(f"{root}/policy", headers={"Authorization": f"Bearer {forged}"})
    assert denied.status_code in {403, 404}
    auth.revoked_at = utcnow()
    value[0].commit()
    assert client.get(f"{root}/policy").status_code == 401


def test_feature_is_absent_by_default_and_runtime_gate_cannot_be_bypassed(case):
    case[4].setattr(get_settings(), "agent_weekly_inspection_enabled", False)
    assert case[1].get(f"{case[2]}/policy").status_code == 404
    app = create_app()
    assert not any("/inspection/weekly/" in path for path in app.openapi()["paths"])


@pytest.mark.parametrize("extra", [
    {"authorizer_user_id": "1"}, {"environment": "prod"}, {"publication_mode": "AUTO"},
    {"current_version": True},
])
def test_policy_input_cannot_override_identity_environment_or_publication(case, extra):
    _, body = arrange(case[0])
    assert case[1].put(f"{case[2]}/policy", json={**body, **extra}).status_code == 422


def test_registration_and_history_are_bounded_and_cannot_select_other_execution_scope(case):
    save(case)
    run = due(case)[0]
    client, root = case[1], case[2]
    assert client.post(f"{root}/due", json={"current_version": 1, "now": "2026"}).status_code == 422
    assert client.get(f"{root}/executions", params={"limit": 101}).status_code == 422
    assert client.get(f"{root}/executions", params={"before_id": 0}).status_code == 422
    assert client.get(f"{root}/executions/9223372036854775808").status_code == 422
    wrong_term = client.get(f"{root}/executions/{run['id']}", params={"semester_id": "999"})
    assert wrong_term.status_code == 404
    wrong_group = root.replace(f"groups/{case[0][4]}", "groups/999")
    assert client.get(wrong_group + "/executions").status_code == 404


def test_detail_rechecks_all_task_visibility_and_reports_expired_draft_without_writing(case):
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
    from app.modules.inspection.models import InspectionTask

    plan = save(case)
    run = due(case)[0]
    service, _ = arrange(case[0])
    generated = service.generate(int(run["id"]))
    ready = service.prepare(int(run["id"]))
    path = f"{case[2]}/executions/{run['id']}"
    current = case[1].get(path)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["can_confirm"] is True
    db = case[0][0]
    draft = db.get(AssignmentConfirmationPlan, ready["assignment_plan_id"])
    draft.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    expired = case[1].get(path).json()["data"]
    assert expired["can_confirm"] is False and expired["requires_recheck"] is True
    assert expired["plan_id"] == plan["id"]
    task = db.get(InspectionTask, int(generated["task_ids"][0]))
    task.group_id = None
    db.commit()
    assert case[1].get(path).status_code == 404
    assert case[1].get(f"{case[2]}/executions").json()["data"]["items"] == []


def test_recheck_is_explicit_and_stale_pointer_retry_does_not_replace_newer_draft(case):
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan

    save(case)
    run = due(case)[0]
    service, _ = arrange(case[0])
    service.generate(int(run["id"]))
    ready = service.prepare(int(run["id"]))
    path = f"{case[2]}/executions/{run['id']}/recheck"
    body = {"expected_assignment_plan_id": ready["assignment_plan_id"]}
    response = case[1].post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["assignment_plan_id"] != ready["assignment_plan_id"]
    count = case[0][0].query(AssignmentConfirmationPlan).count()
    assert case[1].post(path, json=body).status_code == 409
    assert case[0][0].query(AssignmentConfirmationPlan).count() == count


def test_history_keyset_pages_do_not_include_full_draft_or_hidden_counts(case):
    import app.modules.inspection.weekly_service as module

    save(case)
    case[4].setattr(module, "utcnow", lambda: datetime(2026, 9, 14))
    response = case[1].post(f"{case[2]}/due", json={"current_version": 1})
    assert response.status_code == 200 and len(response.json()["data"]) == 2
    first = case[1].get(f"{case[2]}/executions", params={"limit": 1}).json()["data"]
    second = case[1].get(f"{case[2]}/executions", params={
        "limit": 1, "before_id": first["next_before_id"],
    }).json()["data"]
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_before_id"] is None
    assert set(first) == {"items", "next_before_id"}
    assert "result" not in first["items"][0]


def test_real_group_grant_limits_reads_and_another_manager_must_explicitly_recheck(case):
    from app.modules.organization.models import College, ScopedGrant
    from app.modules.organization.service import CampusService

    save(case)
    run = due(case)[0]
    service, _ = arrange(case[0])
    service.generate(int(run["id"]))
    ready = service.prepare(int(run["id"]))
    db, admin, cid, _, gid, *_ = case[0]
    reader = db.scalar(select(UserAccount).where(UserAccount.id != admin.id))
    auth = session_for(db, reader)
    campus = CampusService(db)
    body = {
        "user_id": str(reader.id), "actions": ["inspection.generate", "assignment.manage"],
        "resource_scope": {"kind": "GROUPS", "ids": [str(gid)]},
    }
    campus.create_grant(admin, cid, {
        **body, "preview_revision": campus.preview_grant(admin, cid, body)["revision"],
    })
    token = create_access_token(
        user_id=reader.id, session_id=auth.id, roles=["SUPER_ADMIN"], permissions=["*"],
    )
    case[1].headers["Authorization"] = f"Bearer {token}"
    path = f"{case[2]}/executions/{run['id']}"
    assert case[1].get(f"{case[2]}/policy").status_code == 200
    result = case[1].get(path).json()["data"]
    assert result["can_confirm"] is False and result["requires_recheck"] is True
    new = case[1].post(path + "/recheck", json={
        "expected_assignment_plan_id": ready["assignment_plan_id"],
    })
    assert new.status_code == 200, new.text
    assert case[1].get(path).json()["data"]["can_confirm"] is True
    other_group = campus.create_group(admin, cid, {
        "name": "Outside weekly responsibility", "owner_user_id": str(admin.id),
    })
    outside = case[2].replace(f"groups/{gid}", f"groups/{other_group['id']}")
    assert case[1].get(outside + "/policy").status_code == 404
    assert case[1].get(outside + "/executions").status_code == 404
    other_college = db.scalar(select(College.id).where(College.id != cid))
    assert other_college is not None
    foreign_path = case[2].replace(f"colleges/{cid}", f"colleges/{other_college}")
    assert case[1].get(foreign_path + "/policy").status_code in {403, 404}
    for grant in db.scalars(select(ScopedGrant).where(ScopedGrant.user_id == reader.id)):
        grant.status = "REVOKED"
    db.commit()
    assert case[1].get(path).status_code in {403, 404}


def test_detail_discloses_changed_existing_assignment_without_rewriting_snapshot(case):
    from app.modules.inspection.weekly_models import WeeklyInspectionExecution

    service, eid, ids = weekly_tests.generated_pair(case[0])
    manual = weekly_tests.existing_assignment(case[0], ids[0])
    service.prepare(eid, now=datetime(2026, 9, 4, 8))
    manual.revoked_at = datetime(2026, 9, 4, 9)
    case[0][0].commit()
    row = case[0][0].get(WeeklyInspectionExecution, eid)
    snapshot = row.result_json
    detail = case[1].get(f"{case[2]}/executions/{eid}")
    assert detail.status_code == 200, detail.text
    result = detail.json()["data"]
    assert result["coverage_status"] == "CHANGED"
    assert result["can_confirm"] is False and result["requires_recheck"] is True
    assert result["coverage_changes"][0]["current_assignment_id"] is None
    assert row.result_json == snapshot


@pytest.mark.parametrize("change", ["task_revision", "classification"])
def test_detail_detects_stale_business_revision_without_replacing_or_expiring_draft(case, change):
    from app.core.exceptions import ConflictError
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
    from app.modules.inspection.assignment_plan_service import AssignmentPlanService
    from app.modules.inspection.models import InspectionTask

    save(case)
    run = due(case)[0]
    service, _ = arrange(case[0])
    generated = service.generate(int(run["id"]))
    ready = service.prepare(int(run["id"]))
    db, actor, cid, _, gid, *_ = case[0]
    old = db.get(AssignmentConfirmationPlan, ready["assignment_plan_id"])
    expiry = old.expires_at
    task = db.get(InspectionTask, int(generated["task_ids"][0]))
    if change == "task_revision":
        task.lock_version += 1
    else:
        case[0][6].classification_revision += 1
    db.commit()
    detail = case[1].get(f"{case[2]}/executions/{run['id']}")
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["can_confirm"] is False and data["requires_recheck"] is True
    assert old.expires_at == expiry and old.status == "READY"
    assert db.query(AssignmentConfirmationPlan).count() == 1
    with pytest.raises(ConflictError):
        AssignmentPlanService(db, actor, cid, gid).commit(
            old.id, {"revision": old.revision, "confirmations": []},
        )
