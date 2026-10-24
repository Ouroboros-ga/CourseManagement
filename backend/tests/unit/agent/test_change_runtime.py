from dataclasses import replace
from hashlib import sha256

import pytest
from app.core.exceptions import AppError
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.models import AgentRun
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.run_context import AppConnection, RunService
from app.modules.identity.models import AuthSession
from app.modules.inspection.models import InspectionAssignment
from pydantic import ValidationError


def connection():
    return AppConnection(
        app_key_id="change-app",
        key_digest=sha256(b"c" * 40).hexdigest(),
        entry_kind="AUTOMATION",
        workflow_kind="change",
        environment="dev",
    )


@pytest.fixture
def bound(monkeypatch):
    from tests.unit.agent.test_auto_change import arrange, fixture, request

    source = fixture.__wrapped__(monkeypatch)
    prepared = next(source)
    try:
        db, auto, plans, old, _ = arrange(prepared)
        auto.set_policy(plans.actor, enabled=True, current_version=0)
        execution = auto.register(request(db, old).id)
        db.commit()
        yield db, auto, execution, old
    finally:
        source.close()


def issue(bound):
    db, _, execution, _ = bound
    runs = RunService(db, [connection()], environment="dev")
    run, token = runs.issue_change("change-app", execution.id)
    db.commit()
    return runs, run, token


def test_automation_connections_require_exact_implemented_workflow():
    assert connection().workflow_kind == "change"
    for entry, workflow in [
        ("AUTOMATION", None),
        ("AUTOMATION", "report"),
        ("SELF_SERVICE", "change"),
        ("MANAGEMENT", "change"),
    ]:
        with pytest.raises(ValidationError):
            AppConnection(
                app_key_id="invalid",
                key_digest="c" * 64,
                environment="dev",
                entry_kind=entry,
                workflow_kind=workflow,
            )


def test_policy_run_is_bound_to_real_requester_without_fabricated_session(bound):
    db, auto, execution, old = bound
    before = db.query(AuthSession).count()
    runs = RunService(db, [connection()], environment="dev")
    run, token = runs.issue_change("change-app", execution.id)
    assert run.source_session_id is None
    assert run.actor_user_id == old.volunteer_user_id
    assert run.auto_change_execution_id == execution.id
    assert run.college_id == auto.cid and run.semester_id == auto.sid
    assert run.credential_digest == sha256(token.encode()).hexdigest()
    assert db.query(AuthSession).count() == before
    db.rollback()
    assert db.query(AgentRun).count() == 0


def test_change_tools_use_bound_execution_and_reject_model_identity_fields(bound):
    db, _, _, old = bound
    runs, _, token = issue(bound)
    context = runs.resolve("c" * 40, token)
    assert context.actor.id == old.volunteer_user_id
    assert {s.name for s in ToolRegistry().list_for("AUTOMATION", "change")} == {
        "change_prepare",
        "change_apply",
    }
    assert ToolRegistry().list_for("AUTOMATION") == ()
    assert ToolRegistry().list_for("AUTOMATION", "report") == ()
    for payload in ({"request_id": "1"}, {"actor_user_id": "1"}, {"execution_id": "1"}):
        with pytest.raises(AppError):
            invoke_tool(db, context, "change_prepare", payload)
    prepared = invoke_tool(db, context, "change_prepare", {})
    assert prepared.data["status"] == "PREPARED"
    result = invoke_tool(db, runs.resolve("c" * 40, token), "change_apply", {})
    assert result.data["status"] == "SUCCEEDED"
    assert db.get(InspectionAssignment, old.id).revoked_at is not None
    repeated = invoke_tool(db, runs.resolve("c" * 40, token), "change_apply", {})
    assert repeated.data == result.data


@pytest.mark.parametrize("mutation", ["revoke", "rotate", "binding", "actor"])
def test_stale_or_modified_context_cannot_apply_after_authentication(bound, mutation):
    from app.core.database import utcnow

    db, _, _, old = bound
    runs, run, token = issue(bound)
    context = runs.resolve("c" * 40, token)
    invoke_tool(db, context, "change_prepare", {})
    if mutation == "revoke":
        run.revoked_at = utcnow()
        db.commit()
    elif mutation == "rotate":
        runs.issue_change("change-app", run.auto_change_execution_id)
        db.commit()
    elif mutation == "binding":
        from tests.unit.agent.test_auto_change import request

        _, auto, _, _ = bound
        another = auto.register(request(db, old).id)
        db.commit()
        context = replace(context, auto_change_execution_id=another.id)
    else:
        context = replace(context, college_id=context.college_id + 1)
    with pytest.raises(AppError):
        invoke_tool(db, context, "change_apply", {})
    assert db.get(InspectionAssignment, old.id).revoked_at is None


def test_disabled_policy_cannot_issue_or_resolve_background_identity(bound):
    db, auto, execution, _ = bound
    runs, _, token = issue(bound)
    from app.modules.agent.change_runtime import service_for_execution

    service, _ = service_for_execution(db, execution.id)
    actor = service._authorizer(execution.authorizer_user_id)
    auto.set_policy(actor, enabled=False, current_version=execution.policy_version)
    with pytest.raises(AppError):
        runs.resolve("c" * 40, token)
    with pytest.raises(AppError):
        runs.issue_change("change-app", execution.id)


def test_change_identity_migration_preserves_interactive_runs_and_blocks_history_loss(bound):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.modules.identity.models import UserAccount
    from sqlalchemy import inspect, text
    from tests.unit.agent.test_run_context import connection as self_connection
    from tests.unit.agent.test_run_context import session_for

    db, _, _, old = bound
    user = db.get(UserAccount, old.volunteer_user_id)
    auth = session_for(db, user)
    interactive = RunService(db, [self_connection()], environment="dev")
    original, original_token = interactive.issue("self-app", user.id, auth.id)
    original_id = original.id
    db.commit()
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a004_change_identity.py"
    spec = importlib.util.spec_from_file_location("change_identity_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
        columns = {c["name"]: c for c in inspect(connection).get_columns("agent_run")}
        assert "auto_change_execution_id" not in columns
        assert columns["source_session_id"]["nullable"] is False
        migration.upgrade()
        assert connection.scalar(text("SELECT id FROM agent_run")) == original_id
    db.expire_all()
    assert interactive.resolve("a" * 40, original_token).actor.id == user.id
    db.commit()
    issue(bound)
    with (
        db.bind.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        with pytest.raises(RuntimeError, match="automation"):
            migration.downgrade()
        assert "auto_change_execution_id" in {
            c["name"] for c in inspect(connection).get_columns("agent_run")
        }


def test_http_automation_reaches_only_bound_change_tools(bound, monkeypatch):
    from app.core import database
    from app.core.config import get_settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    db, _, _, old = bound
    _, _, token = issue(bound)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_tool_connections", [connection()])
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    client = TestClient(create_app())
    headers = {"X-Tool-App-Key": "c" * 40, "X-Agent-Run-Token": token}
    base = "/api/v1/agent-tools/v1/calls/"
    assert (
        client.post(
            base + "self_attendance_list", headers=headers, json={"arguments": {}}
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + "change_prepare", headers=headers, json={"arguments": {"request_id": "1"}}
        ).status_code
        == 422
    )
    assert (
        client.post(base + "change_prepare", headers=headers, json={"arguments": {}}).json()[
            "data"
        ]["data"]["status"]
        == "PREPARED"
    )
    result = client.post(base + "change_apply", headers=headers, json={"arguments": {}})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["data"]["status"] == "SUCCEEDED"
    db.expire_all()
    assert db.get(InspectionAssignment, old.id).revoked_at is not None


def test_mcp_network_lists_only_change_tools_and_replays_original_receipt(bound, monkeypatch):
    import asyncio
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from app.core import database
    from app.core.config import get_settings
    from app.main import create_app
    from sqlalchemy.orm import sessionmaker

    db, _, _, old = bound
    _, _, token = issue(bound)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_mcp_enabled", True)
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_tool_connections", [connection()])
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
            "X-Tool-App-Key": "c" * 40,
            "X-Agent-Run-Token": token,
        }
        with httpx.Client(timeout=5) as client:
            url = f"http://127.0.0.1:{port}/mcp/agent-tools"

            def rpc(method, params):
                response = client.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params,
                    },
                )
                assert response.status_code == 200, response.text
                return response.json()["result"]

            rpc(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "bound-change-test", "version": "1"},
                },
            )
            assert {row["name"] for row in rpc("tools/list", {})["tools"]} == {
                "change_prepare",
                "change_apply",
            }
            assert rpc("tools/call", {"name": "system_probe", "arguments": {}})["isError"]
            rpc("tools/call", {"name": "change_prepare", "arguments": {}})
            result = rpc("tools/call", {"name": "change_apply", "arguments": {}})
            assert result["structuredContent"]["data"]["status"] == "SUCCEEDED"
            repeated = rpc("tools/call", {"name": "change_apply", "arguments": {}})
            assert repeated["structuredContent"]["data"] == result["structuredContent"]["data"]
        db.expire_all()
        assert db.get(InspectionAssignment, old.id).revoked_at is not None
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()


@pytest.mark.parametrize("source", ["authorizer", "requester"])
def test_current_source_accounts_must_remain_active(bound, source):
    from app.modules.identity.models import UserAccount

    db, _, execution, old = bound
    runs, _, token = issue(bound)
    uid = execution.authorizer_user_id if source == "authorizer" else old.volunteer_user_id
    user = db.get(UserAccount, uid)
    user.status = "DISABLED"
    db.commit()
    with pytest.raises(AppError):
        runs.resolve("c" * 40, token)


def test_automation_never_uses_interactive_issue_or_read_job_submission(bound):
    from app.modules.agent.task_service import TaskService

    db, _, _, old = bound
    runs, run, _ = issue(bound)
    with pytest.raises(AppError):
        runs.issue("change-app", old.volunteer_user_id, None)
    with pytest.raises(AppError):
        TaskService(db, [connection()], environment="dev").submit(
            run.id, old.volunteer_user_id, None, "change_apply", {}, "bad-read-job"
        )


def test_no_candidate_returns_and_logs_manual_required_without_reassigning(bound, caplog):
    from app.modules.identity.models import UserAccount

    db, _, _, old = bound
    runs, _, token = issue(bound)
    replacement = db.query(UserAccount).filter_by(display_name="Replacement").one()
    replacement.status = "DISABLED"
    db.commit()
    with caplog.at_level("INFO", logger="app.modules.agent.gateway"):
        result = invoke_tool(db, runs.resolve("c" * 40, token), "change_prepare", {})
    assert result.status == "MANUAL_REQUIRED"
    assert caplog.records[-1].status == "MANUAL_REQUIRED"
    assert db.get(InspectionAssignment, old.id).revoked_at is None
