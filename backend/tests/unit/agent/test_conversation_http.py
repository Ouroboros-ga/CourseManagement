import pytest
from app.core import database
from app.core.config import get_settings
from app.main import create_app
from app.modules.agent.adp_chat import AdpChatClient, AdpChatReply
from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.adp_schemas import AdpChatConfiguration
from app.modules.agent.conversation_models import AgentConversation
from app.modules.agent.models import AgentRun
from app.modules.identity.deps import get_current_user, get_session_id
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

ROOT = "/api/v1/assistant/management/conversations"


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_report_export_prepare import fixture as report_fixture

    original = report_fixture.__wrapped__(monkeypatch)
    value = next(original)
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_adp_enabled", True)
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "agent_tool_connections", value[2].connections)
    monkeypatch.setattr(
        settings,
        "agent_management_chat_config",
        AdpChatConfiguration(
            app_key="synthetic-chat-platform-key",
            tool_app_key_id="management",
            header_binding_verified=True,
        ),
    )
    factory = sessionmaker(bind=value[0][1].bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    app = create_app()
    source = value[0][1].query(AgentRun).one()
    app.dependency_overrides[get_current_user] = lambda: value[1]
    app.dependency_overrides[get_session_id] = lambda: source.source_session_id
    calls = []

    def reply(self, text, **kwargs):
        calls.append((text, kwargs))
        return AdpChatReply(
            kwargs["conversation_id"], kwargs["request_id"], "已收到合成问题，请核对业务结果"
        )

    monkeypatch.setattr(AdpChatClient, "chat", reply)
    yield value, TestClient(app), source, calls
    with pytest.raises(StopIteration):
        next(original)


def scope(case):
    return {"college_id": str(case[2].college_id), "semester_id": str(case[2].semester_id)}


def test_login_create_send_and_replay_return_history_without_credentials(case):
    _, client, _, calls = case
    response = client.post(ROOT, json=scope(case))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    conversation = response.json()["data"]
    assert conversation["state"] == "OPEN" and conversation["turns"] == []
    path = f"{ROOT}/{conversation['id']}/messages"
    body = {**scope(case), "text": "合成问题", "request_key": "request-1"}
    sent = client.post(path, json=body)
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["turns"][0]["state"] == "SUCCEEDED"
    assert len(calls) == 1 and calls[0][1]["run_token"] not in sent.text
    assert "synthetic-chat-platform-key" not in sent.text
    repeated = client.post(path, json=body)
    assert repeated.status_code == 200 and len(calls) == 1
    history = client.get(f"{ROOT}/{conversation['id']}", params=scope(case))
    assert history.status_code == 200
    assert history.json()["data"]["turns"] == repeated.json()["data"]["turns"]


def test_route_requires_actual_login(case):
    _, client, _, _ = case
    client.app.dependency_overrides.clear()
    assert client.post(ROOT, json=scope(case)).status_code == 401


def test_unconfigured_chat_is_rejected_before_creating_records(case, monkeypatch):
    value, client, _, _ = case
    monkeypatch.setattr(get_settings(), "agent_management_chat_config", None)
    assert client.post(ROOT, json=scope(case)).status_code == 503
    assert value[0][1].query(AgentConversation).count() == 0


def test_model_identity_or_application_overrides_are_rejected(case):
    _, client, _, _ = case
    assert (
        client.post(
            ROOT, json={**scope(case), "app_key_id": "other", "actor_user_id": "99"}
        ).status_code
        == 422
    )


def test_ambiguous_cloud_result_is_persisted_and_replay_does_not_resend(case, monkeypatch):
    _, client, _, _ = case
    calls = []

    def uncertain(*args, **kwargs):
        calls.append(1)
        raise AdpCallError("CHAT_UPSTREAM_UNCERTAIN", ambiguous=True)

    monkeypatch.setattr(AdpChatClient, "chat", uncertain)
    conversation = client.post(ROOT, json=scope(case)).json()["data"]
    path = f"{ROOT}/{conversation['id']}/messages"
    body = {**scope(case), "text": "合成问题", "request_key": "request-1"}
    first = client.post(path, json=body)
    assert first.status_code == 200
    assert first.json()["data"]["state"] == "UNCERTAIN"
    assert client.post(path, json=body).status_code == 200 and len(calls) == 1
    assert client.post(path, json={**body, "request_key": "next"}).status_code == 409


def test_another_workspace_cannot_read_the_conversation(case):
    _, client, source, _ = case
    conversation = client.post(ROOT, json=scope(case)).json()["data"]
    response = client.get(
        f"{ROOT}/{conversation['id']}",
        params={**scope(case), "college_id": source.college_id + 100},
    )
    assert response.status_code == 404


def test_real_bearer_uses_database_identity_and_revoked_session_is_rejected(case):
    from app.core.database import utcnow
    from app.core.security import create_access_token
    from app.modules.identity.models import AuthSession

    value, client, source, calls = case
    client.app.dependency_overrides.clear()
    token = create_access_token(
        user_id=value[1].id,
        session_id=source.source_session_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(ROOT, json=scope(case), headers=headers)
    assert first.status_code == 200, first.text
    denied = client.post(
        ROOT, json={**scope(case), "college_id": value[0][5]["id"]}, headers=headers
    )
    assert denied.status_code == 403
    auth = value[0][1].get(AuthSession, source.source_session_id)
    auth.revoked_at = utcnow()
    value[0][1].commit()
    assert (
        client.get(
            f"{ROOT}/{first.json()['data']['id']}", params=scope(case), headers=headers
        ).status_code
        == 401
    )
    assert not calls


@pytest.mark.parametrize("invalid", ["01", "0", str(2**63), 1])
def test_workspace_body_ids_are_canonical_bigint_strings(case, invalid):
    assert case[1].post(ROOT, json={**scope(case), "college_id": invalid}).status_code == 422
