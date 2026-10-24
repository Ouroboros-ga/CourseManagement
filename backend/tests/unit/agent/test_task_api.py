import pytest
from app.modules.identity.deps import get_current_user, get_session_id
from tests.unit.agent.test_http_gateway import client_for
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_logged_in_task_submit_status_and_cancel(campus, monkeypatch):
    client, _, run = client_for(campus, monkeypatch)
    client.app.dependency_overrides[get_current_user] = lambda: campus[3]
    client.app.dependency_overrides[get_session_id] = lambda: run.source_session_id
    body = {
        "run_id": str(run.id),
        "tool_name": "system_probe",
        "arguments": {},
        "request_key": "request-1",
    }
    submitted = client.post("/api/v1/assistant/tasks", json=body)
    assert submitted.status_code == 200, submitted.text
    task = submitted.json()["data"]
    assert task["status"] == "QUEUED"
    assert "token" not in submitted.text
    repeated = client.post("/api/v1/assistant/tasks", json=body)
    assert repeated.json()["data"]["task_id"] == task["task_id"]
    assert (
        client.get(f"/api/v1/assistant/tasks/{task['task_id']}").json()["data"]["status"]
        == "QUEUED"
    )
    assert client.post(f"/api/v1/assistant/tasks/{task['task_id']}/cancel").status_code == 200
    assert (
        client.get(f"/api/v1/assistant/tasks/{task['task_id']}").json()["data"]["status"]
        == "CANCELED"
    )
    client.app.dependency_overrides[get_current_user] = lambda: campus[2]
    assert client.get(f"/api/v1/assistant/tasks/{task['task_id']}").status_code == 404
    assert (
        client.post("/api/v1/assistant/tasks", json={**body, "request_key": "foreign"}).status_code
        == 404
    )


def test_task_api_requires_actual_login(campus, monkeypatch):
    client, _, _ = client_for(campus, monkeypatch)
    assert client.get("/api/v1/assistant/tasks/1").status_code == 401
