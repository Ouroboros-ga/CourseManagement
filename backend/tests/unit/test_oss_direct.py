"""OSS 原生签名使用真实 SDK 离线签名；HTTP 守卫复用内存业务数据库。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import alibabacloud_oss_v2 as oss
import pytest
from app.core.exceptions import AppError
from app.modules.file.models import FileObject
from app.modules.file.router import get_service
from app.modules.file.storage import ObjectStorage, _oss_client
from app.modules.identity.service import CurrentUser

from tests.unit.test_oss_file_routes import PNG
from tests.unit.test_oss_file_routes import file_api as file_api_fixture
from tests.unit.test_oss_storage import MemoryClient, settings


@pytest.fixture
def file_api(monkeypatch):
    yield from file_api_fixture.__wrapped__(monkeypatch)


def signing_client():
    cfg = oss.config.load_default()
    cfg.region = "cn-shanghai"
    cfg.endpoint = "https://oss-cn-shanghai.aliyuncs.com"
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider("fake-id", "fake-secret")
    return oss.Client(cfg)


def test_native_signature_uses_public_endpoint_and_private_cache():
    config = settings(OSS_WEB_DIRECT_ENABLED=True)
    config.oss_endpoint = "https://oss-cn-shanghai-internal.aliyuncs.com"
    storage = ObjectStorage(config, client=MemoryClient(), direct_client=signing_client())
    link = storage.presign_direct_get("2026/中文.png", 30)
    parts = urlsplit(link.url)
    assert parts.scheme == "https"
    assert parts.netloc == "test-course.oss-cn-shanghai.aliyuncs.com"
    query = parse_qs(parts.query)
    assert query["response-cache-control"] == ["private, no-store"]
    # 真实桶禁止覆盖 content-type；必须使用上传时已校验的对象 MIME。
    assert "response-content-type" not in query
    assert "x-oss-signature" in query
    assert 0 < (link.expires_at - datetime.now(UTC)).total_seconds() <= 30
    assert storage.presign_get(123, "key", 30).startswith("/api/v1/files/123/download?")


def test_role_credentials_build_a_client_instead_of_returning_credentials(monkeypatch):
    _oss_client.cache_clear()
    monkeypatch.setattr(
        "alibabacloud_credentials.client.Client",
        lambda config: SimpleNamespace(
            get_credential=lambda: SimpleNamespace(
                access_key_id="fake", access_key_secret="fake", security_token="fake"
            )
        ),
    )
    client = _oss_client("cn-shanghai", "https://oss-cn-shanghai.aliyuncs.com", "test-role", 1)
    assert isinstance(client, oss.Client)
    _oss_client.cache_clear()


def test_direct_failure_never_exposes_sdk_url_or_secret():
    client = Mock()
    client.presign.side_effect = RuntimeError("private-signed-url-secret")
    storage = ObjectStorage(settings(), client=MemoryClient(), direct_client=client)
    with pytest.raises(AppError) as caught:
        storage.presign_direct_get("secret.png", 30)
    assert caught.value.http_status == 503
    assert "secret" not in str(caught.value)


def test_object_writes_keep_local_rollback_mirror_and_delete_both(tmp_path):
    config = settings(OSS_LOCAL_MIRROR_ENABLED=True, FILE_LOCAL_STORAGE_DIR=str(tmp_path))
    client = MemoryClient()
    storage = ObjectStorage(config, client=client)
    storage.save("2026/test.png", PNG, "image/png")
    assert (tmp_path / "2026/test.png").read_bytes() == PNG
    assert storage.read("2026/test.png") == PNG
    storage.delete("2026/test.png")
    assert not (tmp_path / "2026/test.png").exists()
    assert not storage.exists("2026/test.png")


def test_web_direct_is_explicit_and_keeps_authorization_and_expiry(file_api, monkeypatch):
    api, db, state, _ = file_api
    monkeypatch.setattr("app.modules.file.storage._oss_client", lambda *args: signing_client())
    service = api.app.dependency_overrides[get_service]()
    monkeypatch.setattr(service._settings, "oss_web_direct_enabled", True)
    uploaded = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("proof.png", PNG, "image/png")},
    )
    file_id = uploaded.json()["data"]["id"]
    assert api.get(f"/api/v1/files/{file_id}/access").json()["data"]["url"].startswith("/api/")
    direct = api.get(f"/api/v1/files/{file_id}/access?delivery=direct")
    assert direct.status_code == 200
    assert (
        urlsplit(direct.json()["data"]["url"]).netloc == "test-course.oss-cn-shanghai.aliyuncs.com"
    )
    row = db.get(FileObject, int(file_id))
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=20)
    db.commit()
    limited = api.get(f"/api/v1/files/{file_id}/access?delivery=direct").json()["data"]
    assert 0 < limited["expires_in"] <= 20
    state["actor"] = CurrentUser(2, "other", "其他人", "ACTIVE", [], [])
    assert api.get(f"/api/v1/files/{file_id}/access?delivery=direct").status_code == 404
    state["actor"] = CurrentUser(1, "test", "测试用户", "ACTIVE", [], [])
    row.status = "PURGED"
    db.commit()
    assert api.get(f"/api/v1/files/{file_id}/access?delivery=direct").status_code == 410


def test_direct_flag_off_falls_back_and_unknown_mode_rejected(file_api):
    api, _, _, _ = file_api
    file_id = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("a.png", PNG, "image/png")},
    ).json()["data"]["id"]
    assert (
        api.get(f"/api/v1/files/{file_id}/access?delivery=direct")
        .json()["data"]["url"]
        .startswith("/api/")
    )
    assert api.get(f"/api/v1/files/{file_id}/access?delivery=invalid").status_code == 422
