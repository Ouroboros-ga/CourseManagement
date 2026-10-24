import pytest
from app.core import database
from app.core.config import get_settings
from app.main import create_app
from app.modules.identity.deps import get_current_user
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from tests.unit.agent.test_precheck_management import fixture as management_fixture


@pytest.fixture(name="case")
def fixture(monkeypatch):
    yield from management_fixture.__wrapped__(monkeypatch)


def client_for(case, monkeypatch):
    db, teacher = case[:2]
    settings = get_settings()
    monkeypatch.setattr(settings, "campus_configuration_enabled", True)
    monkeypatch.setattr(settings, "campus_business_scoped_enabled", True)
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: teacher
    return TestClient(app)


def test_policy_routes_validate_inputs_and_save_with_real_actor(case, monkeypatch):
    client = client_for(case, monkeypatch)
    cid = case[2]
    path = f"/api/v1/colleges/{cid}/objection-precheck-policy"
    read = client.get(path)
    assert read.status_code == 200 and read.json()["data"]["configuration_ready"]
    changed = client.put(path, json={"enabled": True, "current_version": 0})
    assert changed.status_code == 200 and changed.json()["data"]["version"] == 1
    assert client.put(path, json={"enabled": False, "current_version": 0}).status_code == 409
    assert (
        client.put(
            path, json={"enabled": False, "current_version": 1, "authorizer_user_id": "1"}
        ).status_code
        == 422
    )
    assert client.put(path, json={"enabled": "true", "current_version": 1}).status_code == 422


def test_case_status_and_retry_are_scoped_and_replay_safe(case, monkeypatch):
    from tests.unit.agent.test_precheck_management import failed

    db, _, cid, _, obj, foreign = case
    _, _, old, _ = failed(case)
    client = client_for(case, monkeypatch)
    path = f"/api/v1/colleges/{cid}/objections/{obj.id}/precheck"
    read = client.get(path)
    assert read.status_code == 200 and read.json()["data"]["job_id"] == str(old.id)
    first = client.post(path + "/retry", json={"expected_job_id": str(old.id)})
    second = client.post(path + "/retry", json={"expected_job_id": str(old.id)})
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["job_id"] == second.json()["data"]["job_id"]
    assert db.query(ObjectionPrecheckJob).count() == 2
    assert client.get(f"/api/v1/colleges/{cid}/objections/{foreign.id}/precheck").status_code == 404
    assert (
        client.post(
            path + "/retry", json={"expected_job_id": str(old.id), "college_id": "1"}
        ).status_code
        == 422
    )


def test_feature_off_returns_not_found_and_configuration_missing_refuses_enable(case, monkeypatch):
    client = client_for(case, monkeypatch)
    path = f"/api/v1/colleges/{case[2]}/objection-precheck-policy"
    monkeypatch.setattr(get_settings(), "agent_adp_objection_config", None)
    assert client.put(path, json={"enabled": True, "current_version": 0}).status_code == 409
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", False)
    assert client.get(path).status_code == 404
