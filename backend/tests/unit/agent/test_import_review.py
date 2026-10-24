import json
from dataclasses import replace

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.academic.models import VolunteerQualification
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.run_context import RunContext
from app.modules.importer.models import ImportBatch
from sqlalchemy import select
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_importer import prepare, preview


@pytest.fixture(name="case")
def fixture(monkeypatch):
    original = campus_fixture.__wrapped__()
    campus = next(original)
    monkeypatch.setattr(get_settings(), "campus_configuration_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    service, db, own, foreign, sid = prepare(campus)
    context = RunContext("1", "MANAGEMENT", service.actor, service.cid, sid)
    yield service, db, own, foreign, context
    with pytest.raises(StopIteration):
        next(original)


def review(case, ids, context=None, **extra):
    return invoke_tool(
        case[1], context or case[4], "import_preview_review", {"batch_ids": ids, **extra}
    )


def test_review_uses_real_conflicts_without_applying_or_exposing_rows(case):
    service, db, own, foreign, _ = case
    good = preview(service, case[4].semester_id, own.student_no)
    bad = preview(service, case[4].semester_id, foreign.student_no)
    data = review(case, [good.id, bad.id]).data
    assert data["requires_human_confirmation"] is True
    assert data["business_data_applied"] is False
    assert data["semester_id"] == str(case[4].semester_id)
    assert data["can_confirm"] is False
    assert sum(f["error_count"] for f in data["files"]) > 0
    assert data["files"][0]["changes"]["CREATE"] == 1
    serialized = json.dumps(data)
    for secret in (
        json.dumps(own.student_no),
        json.dumps(foreign.student_no),
        "payload_json",
        "revision",
        "before",
        "after",
    ):
        assert secret not in serialized
    assert db.scalar(select(VolunteerQualification.id)) is None
    assert db.get(ImportBatch, int(good.id)).status == "PREVIEW"


@pytest.mark.parametrize("entry", ["SELF_SERVICE", "AUTOMATION"])
def test_non_management_cannot_access_import_tool(case, entry):
    with pytest.raises(AppError) as error:
        review(case, ["1"], replace(case[4], entry_kind=entry))
    assert error.value.http_status == 404


@pytest.mark.parametrize(
    "ids", [[], ["1", "1"], [1], ["01"], [str(2**63)], [str(i) for i in range(1, 102)]]
)
def test_ids_are_bounded_unique_canonical_strings(case, ids):
    with pytest.raises(AppError) as error:
        review(case, ids)
    assert error.value.http_status == 422


@pytest.mark.parametrize("mutation", ["college", "creator", "semester"])
def test_cannot_inspect_other_workspace_or_uploaders_draft(case, mutation):
    service, db, own, _, context = case
    draft = preview(service, context.semester_id, own.student_no)
    batch = db.get(ImportBatch, int(draft.id))
    if mutation == "college":
        from app.modules.organization.models import College

        batch.college_id = db.scalar(select(College.id).where(College.id != service.cid))
    elif mutation == "creator":
        batch.created_by = None
    else:
        context = replace(context, semester_id=context.semester_id + 100)
    db.commit()
    with pytest.raises(AppError) as error:
        review(case, [draft.id], context)
    assert error.value.http_status == 404


def test_model_cannot_supply_approval_or_identity(case):
    with pytest.raises(AppError) as error:
        review(case, ["1"], college_id="2", approve=True)
    assert error.value.http_status == 422


def test_disabled_college_business_is_rejected(case, monkeypatch):
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", False)
    with pytest.raises(AppError) as error:
        review(case, ["1"])
    assert error.value.http_status == 403


def test_real_queue_runs_import_review_without_student_binding(case):
    from hashlib import sha256

    from app.modules.agent.run_context import RunService
    from app.modules.agent.schemas import AppConnection
    from app.modules.agent.task_service import TaskService
    from app.modules.agent.worker import Worker
    from sqlalchemy.orm import sessionmaker
    from tests.unit.agent.test_run_context import session_for

    service, db, own, _, context = case
    draft = preview(service, context.semester_id, own.student_no)
    auth = session_for(db, service.actor)
    connection = AppConnection(
        app_key_id="import-management",
        entry_kind="MANAGEMENT",
        environment="dev",
        key_digest=sha256(b"i" * 40).hexdigest(),
    )
    runs = RunService(db, [connection], environment="dev")
    run, _ = runs.issue(
        connection.app_key_id,
        service.actor.id,
        auth.id,
        college_id=context.college_id,
        semester_id=context.semester_id,
    )
    tasks = TaskService(db, [connection], environment="dev")
    task = tasks.submit(
        run.id,
        service.actor.id,
        auth.id,
        "import_preview_review",
        {"batch_ids": [draft.id]},
        "review-import-1",
    )
    db.commit()
    assert Worker(sessionmaker(bind=db.bind), [connection], environment="dev").run_once()
    result = tasks.read(task.id, service.actor.id)
    assert result["status"] == "SUCCEEDED"
    assert result["result"]["data"]["can_confirm"] is True
    assert db.scalar(select(VolunteerQualification.id)) is None


@pytest.mark.parametrize("mutation", ["expired", "source_changed", "confirmed"])
def test_stale_previews_never_become_confirmable(case, mutation):
    from datetime import timedelta

    from app.core.database import utcnow

    service, db, own, _, context = case
    draft = preview(service, context.semester_id, own.student_no)
    batch = db.get(ImportBatch, int(draft.id))
    if mutation == "expired":
        batch.expires_at = utcnow() - timedelta(seconds=1)
    elif mutation == "confirmed":
        batch.status = "CONFIRMED"
    else:
        own.name = "Changed after preview"
        own.lock_version += 1
    db.commit()
    data = review(case, [draft.id]).data
    assert not data["can_confirm"]
    assert data["files"][0]["error_count"] > 0
    assert db.scalar(select(VolunteerQualification.id)) is None


@pytest.mark.parametrize("removed_action", ["import.execute", "volunteer.manage"])
def test_original_import_and_target_permissions_are_rechecked(case, removed_action):
    from app.modules.organization.models import ScopedGrant

    service, db, own, _, context = case
    draft = preview(service, context.semester_id, own.student_no)
    assert review(case, [draft.id]).data["can_confirm"]
    grants = list(db.scalars(select(ScopedGrant)))
    assert grants
    for grant in grants:
        grant.actions = [action for action in grant.actions if action != removed_action]
    db.commit()
    with pytest.raises(AppError) as error:
        review(case, [draft.id])
    assert error.value.http_status == 403


def test_http_requires_real_run_credentials_and_never_returns_raw_rows(case, monkeypatch):
    from hashlib import sha256

    from app.core import database
    from app.main import create_app
    from app.modules.agent.run_context import RunService
    from app.modules.agent.schemas import AppConnection
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from tests.unit.agent.test_run_context import session_for

    service, db, own, _, context = case
    draft = preview(service, context.semester_id, own.student_no)
    auth = session_for(db, service.actor)
    connection = AppConnection(
        app_key_id="import-http",
        entry_kind="MANAGEMENT",
        environment="dev",
        key_digest=sha256(b"h" * 40).hexdigest(),
    )
    runs = RunService(db, [connection], environment="dev")
    _, token = runs.issue(
        connection.app_key_id,
        service.actor.id,
        auth.id,
        college_id=context.college_id,
        semester_id=context.semester_id,
    )
    monkeypatch.setattr(get_settings(), "agent_tools_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_tool_connections", [connection])
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    client = TestClient(create_app())
    path = "/api/v1/agent-tools/v1/calls/import_preview_review"
    body = {"arguments": {"batch_ids": [draft.id]}}
    assert client.post(path, json=body).status_code == 401
    response = client.post(
        path,
        json=body,
        headers={
            "X-Tool-App-Key": "h" * 40,
            "X-Agent-Run-Token": token,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]["data"]
    assert data["kind"] == "IMPORT_PREVIEW_REVIEW"
    assert data["can_confirm"] is True
    assert "revision" not in data and "payload_json" not in response.text
    assert db.scalar(select(VolunteerQualification.id)) is None
