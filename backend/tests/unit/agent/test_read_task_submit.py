from dataclasses import replace

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.models import AgentJob, AgentRun, AgentTask
from app.modules.agent.task_service import TaskService
from app.modules.agent.worker import Worker
from sqlalchemy.orm import sessionmaker


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_report_export_prepare import fixture as report_fixture

    original = report_fixture.__wrapped__(monkeypatch)
    case = next(original)
    monkeypatch.setattr(get_settings(), "agent_tool_connections", case[2].connections)
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    yield case
    with pytest.raises(StopIteration):
        next(original)


def submit(case, **extra):
    campus, _, runs, token, source = case
    return invoke_tool(
        campus[1],
        runs.resolve("m" * 40, token),
        "read_task_submit",
        {
            "tool_name": "report_attendance_export_prepare",
            "arguments": {"semester_id": str(source.semester_id), "week_no": source.week_no},
            "request_key": "report-1",
            **extra,
        },
    )


def test_model_can_submit_a_real_durable_task_and_receive_fixed_ui_handoff(case):
    data = submit(case).data
    db = case[0][1]
    assert data["kind"] == "TASK_HANDOFF"
    assert data["task_status"] == "QUEUED"
    assert data["open_path"] == f"/dashboard/reports?assistant_task_id={data['task_id']}"
    assert "token" not in str(data) and "sig=" not in str(data)
    job = db.query(AgentJob).one()
    assert job.tool_name == "report_attendance_export_prepare"
    assert db.query(AgentTask).one().status == "QUEUED"
    worker = Worker(sessionmaker(bind=db.bind), case[2].connections, environment="dev")
    assert worker.run_once()
    result = TaskService(db, case[2].connections, environment="dev").read(
        int(data["task_id"]),
        case[1].id,
    )
    assert result["status"] == "SUCCEEDED"
    assert result["result"]["data"]["artifact_status"] == "NOT_GENERATED"
    repeated = submit(case).data
    assert repeated["task_id"] == data["task_id"]
    assert repeated["task_status"] == "SUCCEEDED"


def test_same_request_key_replays_but_changed_arguments_conflict(case):
    first = submit(case).data
    assert submit(case, request_key="REPORT-1").data["task_id"] == first["task_id"]
    with pytest.raises(AppError) as error:
        submit(case, arguments={"semester_id": str(case[4].semester_id), "week_no": 4})
    assert error.value.http_status == 409
    assert case[0][1].query(AgentTask).count() == 1


def test_idempotency_is_namespaced_by_real_run_not_model_supplied_user(case):
    campus, actor, runs, _, source = case
    first = submit(case).data
    run = campus[1].query(AgentRun).one()
    _, token = runs.issue(
        "management",
        actor.id,
        run.source_session_id,
        college_id=run.college_id,
        semester_id=source.semester_id,
    )
    result = submit((campus, actor, runs, token, source)).data
    assert result["task_id"] != first["task_id"]


@pytest.mark.parametrize(
    "extra",
    [
        {"tool_name": "change_apply"},
        {"tool_name": "read_task_submit"},
        {"tool_name": "task_status_get"},
        {"tool_name": "execute_sql"},
        {"run_id": "99"},
        {"actor_user_id": "99"},
        {"open_path": "https://untrusted.invalid"},
        {"request_key": "x" * 33},
        {"arguments": {"batch_ids": ["1"]}},
        {"arguments": {"semester_id": "1", "week_no": 1, "college_id": "99"}},
    ],
)
def test_caller_cannot_choose_privileged_work_identity_or_destination(case, extra):
    with pytest.raises(AppError) as error:
        submit(case, **extra)
    assert error.value.http_status == 422
    assert case[0][1].query(AgentTask).count() == 0


@pytest.mark.parametrize("entry", ["SELF_SERVICE", "AUTOMATION"])
def test_only_management_can_discover_submission(case, entry):
    with pytest.raises(AppError) as error:
        invoke_tool(
            case[0][1],
            replace(case[2].resolve("m" * 40, case[3]), entry_kind=entry),
            "read_task_submit",
            {},
        )
    assert error.value.http_status == 404


def test_submission_tool_itself_can_never_enter_worker_queue(case):
    db = case[0][1]
    run = db.query(AgentRun).one()
    with pytest.raises(AppError) as error:
        TaskService(db, case[2].connections, environment="dev").submit(
            run.id,
            case[1].id,
            run.source_session_id,
            "read_task_submit",
            {
                "tool_name": "report_attendance_export_prepare",
                "arguments": {"semester_id": str(case[4].semester_id), "week_no": 1},
                "request_key": "nested",
            },
            "forbidden-nesting",
        )
    assert error.value.http_status == 422
    assert db.query(AgentTask).count() == 0


def test_submission_respects_existing_run_capacity(case, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_run_max_pending_tasks", 1)
    submit(case)
    with pytest.raises(AppError) as error:
        submit(case, request_key="second")
    assert error.value.http_status == 429


def test_model_cannot_queue_a_report_for_another_semester(case):
    with pytest.raises(AppError) as error:
        submit(case, arguments={"semester_id": str(case[4].semester_id + 100), "week_no": 1})
    assert error.value.http_status == 403
    assert case[0][1].query(AgentTask).count() == 0


def test_revoked_statistics_permission_prevents_admission(case):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    db = case[0][1]
    for binding in db.query(TeacherCollegeBinding).all():
        db.delete(binding)
    db.commit()
    with pytest.raises(AppError) as error:
        submit(case)
    assert error.value.http_status == 403
    assert db.query(AgentTask).count() == 0


def test_import_task_uses_original_owned_preview_and_fixed_review_page(monkeypatch):
    from hashlib import sha256

    from app.modules.agent.run_context import RunService
    from app.modules.agent.schemas import AppConnection
    from tests.unit.agent.test_import_review import fixture as import_fixture
    from tests.unit.agent.test_run_context import session_for
    from tests.unit.test_scoped_importer import preview

    original = import_fixture.__wrapped__(monkeypatch)
    service, db, own, _, context = next(original)
    try:
        draft = preview(service, context.semester_id, own.student_no)
        second_draft = preview(service, context.semester_id, own.student_no)
        auth = session_for(db, service.actor)
        connection = AppConnection(
            app_key_id="import-task",
            entry_kind="MANAGEMENT",
            environment="dev",
            key_digest=sha256(b"i" * 40).hexdigest(),
        )
        monkeypatch.setattr(get_settings(), "agent_tool_connections", [connection])
        monkeypatch.setattr(get_settings(), "app_env", "dev")
        runs = RunService(db, [connection], environment="dev")
        run, token = runs.issue(
            connection.app_key_id,
            service.actor.id,
            auth.id,
            college_id=context.college_id,
            semester_id=context.semester_id,
        )
        result = invoke_tool(
            db,
            runs.resolve("i" * 40, token),
            "read_task_submit",
            {
                "tool_name": "import_preview_review",
                "arguments": {"batch_ids": [second_draft.id, draft.id]},
                "request_key": "review-1",
            },
        ).data
        replay = invoke_tool(
            db,
            runs.resolve("i" * 40, token),
            "read_task_submit",
            {
                "tool_name": "import_preview_review",
                "arguments": {"batch_ids": [draft.id, second_draft.id]},
                "request_key": "review-1",
            },
        ).data
        assert replay["task_id"] == result["task_id"]
        assert (
            result["open_path"]
            == f"/dashboard/academic?tab=imports&assistant_task_id={result['task_id']}"
        )
        assert Worker(sessionmaker(bind=db.bind), [connection], environment="dev").run_once()
        final = invoke_tool(
            db,
            runs.resolve("i" * 40, token),
            "task_status_get",
            {
                "task_id": result["task_id"],
            },
        ).data
        assert final["status"] == "SUCCEEDED"
        assert final["result"]["data"]["requires_human_confirmation"] is True
        assert final["result"]["data"]["business_data_applied"] is False
        assert db.query(AgentTask).one().run_id == run.id
    finally:
        with pytest.raises(StopIteration):
            next(original)


def test_http_submission_requires_bound_credentials_and_replays_same_task(case, monkeypatch):
    from app.core import database
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    factory = sessionmaker(bind=case[0][1].bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    client = TestClient(create_app())
    path = "/api/v1/agent-tools/v1/calls/read_task_submit"
    body = {
        "arguments": {
            "tool_name": "report_attendance_export_prepare",
            "arguments": {"semester_id": str(case[4].semester_id), "week_no": 1},
            "request_key": "http-task",
        }
    }
    assert client.post(path, json=body).status_code == 401
    headers = {"X-Tool-App-Key": "m" * 40, "X-Agent-Run-Token": case[3]}
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(path, json=body, headers=headers)
    assert second.status_code == 200
    assert first.json()["data"]["data"]["task_id"] == second.json()["data"]["data"]["task_id"]
    assert case[3] not in first.text
    assert case[0][1].query(AgentTask).count() == 1


def test_mcp_real_network_can_submit_a_task_with_nested_strict_arguments(case, monkeypatch):
    import asyncio
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from app.core import database
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "agent_tools_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_mcp_enabled", True)
    factory = sessionmaker(bind=case[0][1].bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    app = create_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        url = f"http://127.0.0.1:{port}/mcp/agent-tools"
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
            "X-Tool-App-Key": "m" * 40,
            "X-Agent-Run-Token": case[3],
        }
        with httpx.Client(timeout=5) as client:
            listing = client.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            assert listing.status_code == 200
            tools = {tool["name"]: tool for tool in listing.json()["result"]["tools"]}
            assert "read_task_submit" in tools
            assert tools["read_task_submit"]["inputSchema"]["additionalProperties"] is False
            response = client.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "read_task_submit",
                        "arguments": {
                            "tool_name": "report_attendance_export_prepare",
                            "arguments": {"semester_id": str(case[4].semester_id), "week_no": 1},
                            "request_key": "mcp-report",
                        },
                    },
                },
            )
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert not result.get("isError")
            assert result["structuredContent"]["data"]["task_status"] == "QUEUED"
            assert case[3] not in response.text
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()
