import pytest
from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import create_app
from app.modules.agent.adp_schemas import AdpChatConfiguration
from app.modules.agent.models import AgentRun
from app.modules.file import storage as storage_module
from fastapi.testclient import TestClient

ROOT = "/api/v1/assistant/management/imports"


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from app.core.database import get_db
    from tests.unit.agent.test_import_workspace import Storage
    from tests.unit.agent.test_import_workspace import fixture as workspace_fixture

    original = workspace_fixture.__wrapped__(monkeypatch)
    value = next(original)
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "agent_management_chat_config",
        AdpChatConfiguration(app_key="synthetic-platform-key", tool_app_key_id="management"),
    )
    blob = Storage()
    monkeypatch.setattr(storage_module, "build_default_storage", lambda settings: blob)
    # Service imports bind at import time, so cover both construction paths.
    from app.modules.agent import import_workspace

    monkeypatch.setattr(import_workspace, "build_default_storage", lambda settings: blob)
    app = create_app()

    def db():
        yield value[0][1]

    app.dependency_overrides[get_db] = db
    source = value[0][1].query(AgentRun).one()
    token = create_access_token(
        user_id=value[1].id,
        session_id=source.source_session_id,
        roles=["SUPER_ADMIN"],
        permissions=["*"],
    )
    yield value, TestClient(app), blob, {"Authorization": f"Bearer {token}"}, source
    with pytest.raises(StopIteration):
        next(original)


def scope(case):
    return {"college_id": str(case[4].college_id), "semester_id": str(case[4].semester_id)}


def send(case, **extra):
    return case[1].post(
        ROOT,
        data={**scope(case), "request_key": "upload-1", **extra},
        files={"file": ("教师.csv", "工号,姓名\n00123,合成教师\n".encode(), "text/csv")},
        headers=case[3],
    )


def test_real_bearer_upload_read_cancel_and_replay_are_owned_and_private(case):
    response = send(case)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    result = response.json()["data"]
    assert result["state"] == "QUEUED" and "object_key" not in response.text
    assert send(case).json()["data"]["workspace_id"] == result["workspace_id"]
    read = case[1].get(f"{ROOT}/{result['workspace_id']}", params=scope(case), headers=case[3])
    assert read.status_code == 200
    cancel = case[1].post(
        f"{ROOT}/{result['workspace_id']}/cancel", json=scope(case), headers=case[3]
    )
    assert cancel.status_code == 200 and cancel.json()["data"]["state"] == "CANCELED"


def test_forged_super_role_does_not_authorize_other_college_and_logout_denies_read(case):
    from app.core.database import utcnow
    from app.modules.identity.models import AuthSession

    response = send(case)
    assert response.status_code == 200, response.text
    assert send(case, college_id=str(case[0][0][5]["id"])).status_code == 403
    auth = case[0][0][1].get(AuthSession, case[4].source_session_id)
    auth.revoked_at = utcnow()
    case[0][0][1].commit()
    assert (
        case[1]
        .get(
            f"{ROOT}/{response.json()['data']['workspace_id']}", params=scope(case), headers=case[3]
        )
        .status_code
        == 401
    )


def test_login_feature_gate_and_strict_upload_fields(case, monkeypatch):
    assert (
        case[1]
        .post(
            ROOT, data={**scope(case), "request_key": "one"}, files={"file": ("one.csv", b"data")}
        )
        .status_code
        == 401
    )
    assert send(case, actor_user_id="1").status_code == 422
    assert send(case, college_id="01").status_code == 422
    monkeypatch.setattr(get_settings(), "agent_import_workspace_enabled", False)
    assert send(case).status_code == 404
