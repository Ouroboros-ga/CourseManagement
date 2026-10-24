from hashlib import sha256

import pytest
from app.core.config import get_settings
from app.main import create_app
from app.modules.agent.run_context import AppConnection, RunService
from fastapi.testclient import TestClient
from tests.unit.agent.test_run_context import session_for
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def client_for(campus, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    connection = AppConnection(
        app_key_id="self",
        entry_kind="SELF_SERVICE",
        environment=settings.app_env,
        key_digest=sha256(("a" * 40).encode()).hexdigest(),
    )
    monkeypatch.setattr(settings, "agent_tool_connections", [connection])
    db, user = campus[1], campus[3]
    auth = session_for(db, user)
    run, token = RunService(db, [connection], environment=settings.app_env).issue(
        "self", user.id, auth.id
    )
    app = create_app()
    from app.core import database
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    headers = {"X-Tool-App-Key": "a" * 40, "X-Agent-Run-Token": token}
    return TestClient(app), headers, run


def test_probe_authenticates_run_and_returns_no_identity(campus, monkeypatch):
    client, headers, _ = client_for(campus, monkeypatch)
    response = client.post(
        "/api/v1/agent-tools/v1/calls/system_probe", headers=headers, json={"arguments": {}}
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "SUCCEEDED"
    assert result["data"] == {"contract_version": "v1"}
    assert result["trace_id"]


def test_unauthenticated_call_never_reaches_tool(campus, monkeypatch):
    client, _, _ = client_for(campus, monkeypatch)
    response = client.post("/api/v1/agent-tools/v1/calls/system_probe", json={"arguments": {}})
    assert response.status_code == 401


def test_self_run_cannot_call_management_tool(campus, monkeypatch):
    client, headers, _ = client_for(campus, monkeypatch)
    response = client.post(
        "/api/v1/agent-tools/v1/calls/report_attendance_summary",
        headers=headers,
        json={"arguments": {"semester_id": "1", "week_no": 1}},
    )
    assert response.status_code == 404


def test_parameters_cannot_override_actor(campus, monkeypatch):
    client, headers, _ = client_for(campus, monkeypatch)
    response = client.post(
        "/api/v1/agent-tools/v1/calls/self_attendance_list",
        headers=headers,
        json={"arguments": {"student_id": "999"}},
    )
    assert response.status_code == 422
    assert headers["X-Agent-Run-Token"] not in response.text


def test_disabled_gateway_has_no_routes(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_tools_enabled", False)
    with TestClient(create_app()) as client:
        assert client.post("/api/v1/agent-tools/v1/calls/system_probe").status_code == 404


def test_oversized_body_is_rejected_before_json_parsing(campus, monkeypatch):
    client, headers, _ = client_for(campus, monkeypatch)
    response = client.post(
        "/api/v1/agent-tools/v1/calls/system_probe",
        headers=headers,
        content=b"x" * (256 * 1024 + 1),
    )
    assert response.status_code == 413
