from dataclasses import replace
from hashlib import sha256

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError
from app.modules.agent.contract_export import build_contract
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.http_router import execute_with_session
from app.modules.agent.models import AgentRun
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.run_context import AppConnection, RunService
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import AuthSession
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result


@pytest.fixture(name="case")
def fixture(monkeypatch):
    yield from case_fixture.__wrapped__(monkeypatch)


def connection():
    return AppConnection(
        app_key_id="objection-app",
        key_digest=sha256(b"o" * 40).hexdigest(),
        entry_kind="AUTOMATION",
        workflow_kind="objection",
        environment="dev",
    )


def issue(case):
    svc, job = queue(case)
    svc.begin(job.id)
    runs = RunService(case[0], [connection()], environment="dev")
    run, token = runs.issue_objection("objection-app", job.id)
    case[0].commit()
    return svc, job, runs, run, token


def test_issue_is_flush_only_with_real_initiator_and_no_fake_session(case):
    db, teacher, cid, _, _, _ = case
    svc, job = queue(case)
    svc.begin(job.id)
    before = db.query(AuthSession).count()
    run, token = RunService(db, [connection()], environment="dev").issue_objection(
        "objection-app", job.id
    )
    assert run.source_session_id is None and run.actor_user_id == teacher.id
    assert run.college_id == cid and run.objection_precheck_job_id == job.id
    assert run.objection_precheck_attempt_digest == sha256(job.attempt_token.encode()).hexdigest()
    assert run.credential_digest == sha256(token.encode()).hexdigest()
    assert db.query(AuthSession).count() == before
    db.rollback()
    assert db.query(AgentRun).count() == 0


def test_only_three_bound_tools_visible_and_identity_arguments_rejected(case):
    db = case[0]
    _, _, runs, _, token = issue(case)
    context = runs.resolve("o" * 40, token)
    assert {s.name for s in ToolRegistry().list_for("AUTOMATION", "objection")} == {
        "objection_case_get",
        "objection_material_access",
        "objection_precheck_save",
    }
    for name in ("change_apply", "report_attendance_summary", "self_attendance_list"):
        with pytest.raises(NotFoundError):
            invoke_tool(db, context, name, {})
    for payload in ({"objection_id": "1"}, {"college_id": "1"}, {"actor_user_id": "1"}):
        with pytest.raises(AppError):
            invoke_tool(db, context, "objection_case_get", payload)
    assert invoke_tool(db, context, "objection_case_get", {}).data["reason"] == ""


def test_save_tool_preserves_formal_state_and_closes_material_access(case):
    db, _, _, _, obj, _ = case
    _, job, runs, _, token = issue(case)
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    before = (record.effective_type, record.current_version, obj.final_status, obj.initial_status)
    context = runs.resolve("o" * 40, token)
    saved = invoke_tool(db, context, "objection_precheck_save", {"result": result().model_dump()})
    assert saved.data["status"] == "SUCCEEDED" and job.status == "SUCCEEDED"
    assert (
        record.effective_type,
        record.current_version,
        obj.final_status,
        obj.initial_status,
    ) == before
    with pytest.raises(AppError):
        invoke_tool(db, context, "objection_case_get", {})
    repeated = invoke_tool(
        db,
        runs.resolve("o" * 40, token),
        "objection_precheck_save",
        {"result": result().model_dump()},
    )
    assert repeated.data == saved.data


@pytest.mark.parametrize("mutation", ["rotate", "revoke", "binding", "scope", "attempt"])
def test_old_or_tampered_context_is_fenced_before_material_or_result(case, mutation):
    db = case[0]
    _, job, runs, run, token = issue(case)
    context = runs.resolve("o" * 40, token)
    if mutation == "rotate":
        runs.issue_objection("objection-app", job.id)
    elif mutation == "revoke":
        from app.core.database import utcnow

        run.revoked_at = utcnow()
    elif mutation == "binding":
        context = replace(context, objection_precheck_job_id=job.id + 1)
    elif mutation == "scope":
        context = replace(context, college_id=context.college_id + 1)
    else:
        job.attempt_token = "f" * 64
    db.commit()
    with pytest.raises(AppError):
        invoke_tool(db, context, "objection_case_get", {})
    assert job.result_json is None


def test_http_adapter_restores_bound_identity_without_model_supplied_scope(case, monkeypatch):
    db = case[0]
    _, job, _, _, token = issue(case)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_tool_connections", [connection()])
    reply = execute_with_session(db, "objection_case_get", {}, "o" * 40, token, "synthetic-trace")
    assert reply["data"]["data"]["objection_id"] == str(job.objection_id)


def test_wrong_app_or_environment_cannot_issue_precheck_identity(case):
    from tests.unit.agent.test_change_runtime import connection as change_connection

    db = case[0]
    svc, job = queue(case)
    svc.begin(job.id)
    with pytest.raises(AppError):
        RunService(db, [change_connection()], environment="dev").issue_objection(
            "change-app", job.id
        )
    with pytest.raises(AppError):
        RunService(
            db, [connection().model_copy(update={"environment": "prod"})], environment="prod"
        ).issue_objection("objection-app", job.id)


def test_objection_contract_is_independent_and_nested_schema_is_self_contained():
    contract = build_contract(workflow_kind="objection")
    names = {p.rsplit("/", 1)[-1] for p in contract["paths"]}
    assert names == {"objection_case_get", "objection_material_access", "objection_precheck_save"}
    assert "$ref" not in str(contract)


def test_student_initiator_is_preserved_without_using_student_as_policy_authorizer(
    case, monkeypatch
):
    from app.modules.objection.precheck_models import ObjectionPrecheckJob
    from app.modules.objection.precheck_service import ObjectionPrecheckService
    from app.modules.objection.schemas import ObjectionCreateRequest
    from sqlalchemy import select
    from tests.unit.agent.test_objection_precheck import student_case

    db, teacher, cid, _, _, _ = case
    svc = ObjectionPrecheckService(db, cid)
    svc.set_policy(teacher, enabled=True, current_version=0)
    original, student, record_id = student_case(case, monkeypatch)
    original.create(
        student, record_id, ObjectionCreateRequest(reason="误记", desired_type="NORMAL"), None
    )
    job = db.scalar(select(ObjectionPrecheckJob))
    svc.begin(job.id)
    runs = RunService(db, [connection()], environment="dev")
    run, token = runs.issue_objection("objection-app", job.id)
    db.commit()
    context = runs.resolve("o" * 40, token)
    assert run.actor_user_id == student.id and job.authorizer_user_id == teacher.id
    assert "TEACHER_ADMIN" not in context.actor.roles
    assert invoke_tool(db, context, "objection_case_get", {}).data["reason"] == "误记"


def test_changed_source_at_save_returns_manual_required_not_fake_success(case):
    db, _, _, _, obj, _ = case
    _, job, runs, _, token = issue(case)
    context = runs.resolve("o" * 40, token)
    obj.reason = "补充新理由"
    db.commit()
    saved = invoke_tool(db, context, "objection_precheck_save", {"result": result().model_dump()})
    assert saved.status == "MANUAL_REQUIRED"
    assert saved.data["precheck_status"] == "STALE" and job.result_json is None


def test_database_rejects_incomplete_or_mixed_background_identity(case):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    db = case[0]
    _, _, _, run, _ = issue(case)
    with pytest.raises(IntegrityError):
        db.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(objection_precheck_job_id=None)
        )
    db.rollback()
    with pytest.raises(IntegrityError):
        db.execute(update(AgentRun).where(AgentRun.id == run.id).values(workflow_kind="change"))
    db.rollback()


def test_identity_migration_preserves_old_columns_and_guards_precheck_history(case):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.modules.identity.models import UserAccount
    from sqlalchemy import inspect
    from tests.unit.agent.test_run_context import connection as self_connection
    from tests.unit.agent.test_run_context import session_for

    db = case[0]
    path = Path(__file__).parents[3] / "migrations/versions/f26a1024a008_objection_identity.py"
    spec = importlib.util.spec_from_file_location("objection_identity_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    user = db.get(UserAccount, case[1].id)
    auth = session_for(db, user)
    interactive = RunService(db, [self_connection()], environment="dev")
    old_run, old_token = interactive.issue("self-app", user.id, auth.id)
    old_id = old_run.id
    db.commit()
    with db.bind.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
        assert "objection_precheck_job_id" not in {
            c["name"] for c in inspect(conn).get_columns("agent_run")
        }
        assert "auto_change_execution_id" in {
            c["name"] for c in inspect(conn).get_columns("agent_run")
        }
        migration.upgrade()
    db.expire_all()
    assert interactive.resolve("a" * 40, old_token).run_id == str(old_id)
    db.commit()
    issue(case)
    with (
        db.bind.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
        pytest.raises(RuntimeError, match="precheck"),
    ):
        migration.downgrade()


def test_real_mcp_network_lists_only_precheck_tools_and_saves_advice(case, monkeypatch, caplog):
    import asyncio
    import logging
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from app.core import database
    from app.main import create_app
    from sqlalchemy.orm import sessionmaker
    from tests.unit.agent.test_objection_precheck_materials import SigningStorage, proof

    db, teacher, _, _, obj, _ = case
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    file = proof(db, obj, teacher.id)
    _, job, _, _, token = issue(case)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_mcp_enabled", True)
    monkeypatch.setattr(settings, "agent_tool_connections", [connection()])
    storage = SigningStorage()
    monkeypatch.setattr("app.modules.file.service.build_default_storage", lambda _: storage)
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    caplog.set_level(logging.DEBUG, logger="mcp")
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
            "X-Tool-App-Key": "o" * 40,
            "X-Agent-Run-Token": token,
        }
        with httpx.Client(timeout=5) as client:

            def rpc(index, method, params):
                response = client.post(
                    url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": method,
                        "params": params,
                    },
                )
                assert response.status_code == 200
                return response.json()["result"]

            rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-precheck", "version": "1"},
                },
            )
            names = {t["name"] for t in rpc(2, "tools/list", {})["tools"]}
            assert names == {
                "objection_case_get",
                "objection_material_access",
                "objection_precheck_save",
            }
            case_reply = rpc(3, "tools/call", {"name": "objection_case_get", "arguments": {}})
            assert case_reply["structuredContent"]["data"]["objection_id"] == str(job.objection_id)
            material = rpc(
                4,
                "tools/call",
                {
                    "name": "objection_material_access",
                    "arguments": {"file_id": str(file.id)},
                },
            )
            assert material["structuredContent"]["data"]["expires_in"] == 60
            hidden = rpc(5, "tools/call", {"name": "change_apply", "arguments": {}})
            assert hidden["isError"]
            saved = rpc(
                6,
                "tools/call",
                {
                    "name": "objection_precheck_save",
                    "arguments": {"result": result().model_dump()},
                },
            )
            assert saved["structuredContent"]["data"]["status"] == "SUCCEEDED"
            replay = rpc(
                7,
                "tools/call",
                {
                    "name": "objection_precheck_save",
                    "arguments": {"result": result().model_dump()},
                },
            )
            assert replay["structuredContent"]["data"]["status"] == "SUCCEEDED"
            closed = rpc(8, "tools/call", {"name": "objection_case_get", "arguments": {}})
            assert closed["isError"]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()
    db.refresh(job)
    assert job.status == "SUCCEEDED" and obj.final_status == "PENDING"
    assert "must-not-persist" not in caplog.text and token not in caplog.text
    assert "o" * 40 not in caplog.text


def test_completed_advice_rejects_changed_replay_without_overwriting_result(case):
    db = case[0]
    _, job, runs, run, token = issue(case)
    invoke_tool(
        db,
        runs.resolve("o" * 40, token),
        "objection_precheck_save",
        {"result": result().model_dump()},
    )
    assert run.status == "COMPLETED"
    altered = {**result().model_dump(), "summary": "不同建议"}
    with pytest.raises(AppError):
        invoke_tool(
            db, runs.resolve("o" * 40, token), "objection_precheck_save", {"result": altered}
        )
    assert job.result_json["summary"] == result().summary


def test_advice_and_completed_run_receipt_rollback_together(case, monkeypatch):
    db = case[0]
    _, job, runs, run, token = issue(case)
    context = runs.resolve("o" * 40, token)

    def fail_commit():
        raise RuntimeError("synthetic receipt commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic receipt"):
            invoke_tool(db, context, "objection_precheck_save", {"result": result().model_dump()})
    db.refresh(job)
    db.refresh(run)
    assert job.status == "RUNNING" and job.result_json is None
    assert run.status == "ACTIVE"


@pytest.mark.parametrize("mutation", ["expire", "revoke", "policy"])
def test_completed_receipt_still_requires_live_credential_and_current_policy(case, mutation):
    from datetime import timedelta

    from app.core.database import utcnow

    db, teacher, _, _, _, _ = case
    svc, _, runs, run, token = issue(case)
    invoke_tool(
        db,
        runs.resolve("o" * 40, token),
        "objection_precheck_save",
        {"result": result().model_dump()},
    )
    if mutation == "expire":
        run.credential_expires_at = utcnow() - timedelta(seconds=1)
    elif mutation == "revoke":
        run.revoked_at = utcnow()
    else:
        svc.set_policy(teacher, enabled=False, current_version=1)
    db.commit()
    with pytest.raises(AppError):
        runs.resolve("o" * 40, token)


def test_completed_receipt_reports_stale_source_without_rewriting_history(case):
    db, _, _, _, obj, _ = case
    _, job, runs, _, token = issue(case)
    invoke_tool(
        db,
        runs.resolve("o" * 40, token),
        "objection_precheck_save",
        {"result": result().model_dump()},
    )
    obj.reason = "后补说明"
    db.commit()
    replay = invoke_tool(
        db,
        runs.resolve("o" * 40, token),
        "objection_precheck_save",
        {"result": result().model_dump()},
    )
    assert replay.status == "MANUAL_REQUIRED" and replay.data["precheck_status"] == "STALE"
    assert job.status == "SUCCEEDED" and job.result_json["summary"] == result().summary
