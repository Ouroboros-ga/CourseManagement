from contextlib import contextmanager
from datetime import datetime

import pytest
from app.core.config import get_settings
from app.modules.agent.adp_chat import AdpChatClient, AdpChatReply
from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.chat_pool import capacity_guard
from app.modules.agent.chat_worker import ChatWorker
from app.modules.agent.conversation_models import AgentTurn
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.run_context import RunService
from app.modules.agent.worker import Worker
from sqlalchemy.orm import sessionmaker
from tests.unit.agent.test_conversation_http import ROOT, scope, worker


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_conversation_http import fixture as http_fixture

    original = http_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def submit(case):
    client = case[1]
    conversation = client.post(ROOT, json=scope(case)).json()["data"]
    response = client.post(
        f"{ROOT}/{conversation['id']}/messages",
        json={**scope(case), "text": "请汇总本周考勤", "request_key": "one"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["turns"][0]["state"] == "QUEUED"
    return conversation["id"]


def read(case, conversation_id):
    return case[1].get(f"{ROOT}/{conversation_id}", params=scope(case)).json()["data"]


def test_paused_provider_leaves_queue_untouched_and_can_resume(case, monkeypatch):
    conversation_id = submit(case)
    monkeypatch.setattr(get_settings(), "agent_adp_enabled", False)
    assert not worker(case).run_once()
    assert read(case, conversation_id)["turns"][0]["state"] == "QUEUED"
    assert case[3] == []
    monkeypatch.setattr(get_settings(), "agent_adp_enabled", True)
    assert worker(case).run_once()
    assert read(case, conversation_id)["turns"][0]["state"] == "SUCCEEDED"


def test_provider_io_holds_neither_database_session_nor_capacity_guard(case, monkeypatch):
    conversation_id = submit(case)
    factory = sessionmaker(bind=case[0][0][1].bind)
    active = []

    @contextmanager
    def tracked_sessions():
        with factory() as db:
            active.append(db)
            try:
                yield db
            finally:
                active.remove(db)

    def reply(self, question, **kwargs):
        assert not active
        with factory() as db, capacity_guard(db, "dev", "management") as guard:
            assert guard is not None
        return AdpChatReply(kwargs["conversation_id"], kwargs["request_id"], "合成回复")

    monkeypatch.setattr(AdpChatClient, "chat", reply)
    consumer = ChatWorker(
        tracked_sessions, case[0][2].connections, environment="dev", app_key_id="management"
    )
    assert consumer.run_once()
    assert read(case, conversation_id)["turns"][0]["state"] == "SUCCEEDED"


def test_chat_can_wait_for_independent_read_consumer_and_returns_real_handoff(case, monkeypatch):
    conversation_id = submit(case)
    factory = sessionmaker(bind=case[0][0][1].bind)
    connections = case[0][2].connections
    handoffs = []

    def reply(self, question, **kwargs):
        with factory() as db:
            context = RunService(db, connections, environment="dev").resolve(
                "m" * 40, kwargs["run_token"]
            )
            result = invoke_tool(
                db,
                context,
                "read_task_submit",
                {
                    "tool_name": "report_attendance_export_prepare",
                    "arguments": {
                        "semester_id": str(case[2].semester_id),
                        "week_no": case[0][4].week_no,
                    },
                    "request_key": "child-report",
                },
            ).data
            handoffs.append(result)
        assert Worker(factory, connections, environment="dev").run_once()
        with factory() as db:
            context = RunService(db, connections, environment="dev").resolve(
                "m" * 40, kwargs["run_token"]
            )
            status = invoke_tool(
                db, context, "task_status_get", {"task_id": result["task_id"]}
            ).data
            assert status["status"] == "SUCCEEDED"
        return AdpChatReply(
            kwargs["conversation_id"], kwargs["request_id"], "报表已经准备好，请确认下载"
        )

    monkeypatch.setattr(AdpChatClient, "chat", reply)
    assert worker(case).run_once()
    turn = read(case, conversation_id)["turns"][0]
    assert turn["state"] == "SUCCEEDED"
    assert turn["actions"][0]["task_id"] == handoffs[0]["task_id"]


def test_business_date_uses_request_day_when_queue_crosses_midnight(case, monkeypatch):
    conversation_id = submit(case)
    db = case[0][0][1]
    turn = db.query(AgentTurn).one()
    turn.created_at = datetime(2026, 10, 24, 16, 30)
    db.commit()
    assert worker(case).run_once()
    assert case[3][0][1]["business_context"].business_date.isoformat() == "2026-10-25"
    assert read(case, conversation_id)["turns"][0]["state"] == "SUCCEEDED"


def test_unknown_remote_result_is_not_retried_after_worker_restart(case, monkeypatch):
    conversation_id = submit(case)
    calls = []

    def uncertain(self, *args, **kwargs):
        calls.append(kwargs["request_id"])
        raise AdpCallError("CHAT_TIMEOUT", ambiguous=True)

    monkeypatch.setattr(AdpChatClient, "chat", uncertain)
    assert worker(case).run_once()
    assert not worker(case).run_once()
    assert len(calls) == 1
    assert read(case, conversation_id)["turns"][0]["state"] == "UNCERTAIN"


def test_known_failure_releases_capacity_for_next_conversation(case, monkeypatch):
    first = submit(case)
    second = submit(case)
    calls = []

    def rejected(self, *args, **kwargs):
        calls.append(kwargs["request_id"])
        raise AdpCallError("CHAT_REJECTED")

    monkeypatch.setattr(AdpChatClient, "chat", rejected)
    assert worker(case).run_once() and worker(case).run_once()
    assert len(calls) == 2
    assert read(case, first)["turns"][0]["state"] == "FAILED"
    assert read(case, second)["turns"][0]["state"] == "FAILED"
