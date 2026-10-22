"""SQLite + 模拟 OSS 的 HTTP 文件闭环，不连接 MySQL 或真实云端。"""

import base64
from unittest.mock import Mock

import app.models  # noqa: F401 - 注册关联模型
import pytest
from app.core.database import Base
from app.main import create_app
from app.modules.file.models import FileObject
from app.modules.file.router import get_service
from app.modules.file.service import FileService
from app.modules.file.storage import ObjectStorage
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import UserAccount
from app.modules.identity.service import CurrentUser
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from tests.unit.test_oss_storage import MemoryClient, settings

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS9sAAAAASUVORK5CYII="
)


@pytest.fixture
def file_api(monkeypatch):
    configuration = settings()
    monkeypatch.setattr("app.modules.file.service.get_settings", lambda: configuration)
    monkeypatch.setattr("app.modules.file.router.get_settings", lambda: configuration)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    client = MemoryClient()
    storage = ObjectStorage(configuration, client=client)
    actor = CurrentUser(1, "test", "测试用户", "ACTIVE", [], [])
    state = {"actor": actor}
    with Session(engine) as session:
        from app.modules.identity.models import Role
        from app.modules.identity.seed import sync_registry

        sync_registry(session)
        role = session.scalar(select(Role).where(Role.code == "STUDENT"))
        session.add(
            UserAccount(
                id=1, username="test", display_name="测试用户", status="ACTIVE", roles=[role]
            )
        )
        session.commit()
        service = FileService(session, storage)
        app = create_app()
        app.dependency_overrides[get_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: state["actor"]
        with TestClient(app) as api:
            yield api, session, state, client
    engine.dispose()


def test_upload_access_download_and_authorization(file_api):
    api, session, state, client = file_api
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("中文证明.png", PNG, "image/png")},
    )
    assert response.status_code == 200
    file_id = response.json()["data"]["id"]
    assert isinstance(file_id, str)
    assert len(client.objects) == 1
    assert session.scalar(select(func.count()).select_from(FileObject)) == 1
    access = api.get(f"/api/v1/files/{file_id}/access")
    assert access.status_code == 200
    url = access.json()["data"]["url"]
    downloaded = api.get(url)
    assert downloaded.status_code == 200
    assert downloaded.content == PNG
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert api.get(url.rsplit("sig=", 1)[0] + "sig=forged").status_code == 403
    assert api.get(f"/api/v1/files/{file_id}/download?expires=0&sig=forged").status_code == 403
    state["actor"] = CurrentUser(2, "other", "他人", "ACTIVE", [], [])
    assert api.get(f"/api/v1/files/{file_id}/access").status_code == 404


def test_storage_failure_creates_no_ready_row(file_api):
    api, session, state, client = file_api
    client.put_object = Mock(side_effect=RuntimeError("secret-token"))
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("proof.png", PNG, "image/png")},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert "secret-token" not in response.text
    assert session.scalar(select(func.count()).select_from(FileObject)) == 0


def test_upload_size_and_binding_guard(file_api, monkeypatch):
    api, session, state, client = file_api
    small = settings(FILE_MAX_BYTES=10)
    monkeypatch.setattr("app.modules.file.router.get_settings", lambda: small)
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("proof.png", PNG, "image/png")},
    )
    assert response.status_code == 422
    assert not client.objects
    state["actor"] = CurrentUser(1, "test", "未绑定", "ACTIVE", [], [], pre_binding=True)
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("proof.png", PNG, "image/png")},
    )
    assert response.status_code == 403


def test_upload_normalizes_mismatched_extension_and_mime(file_api):
    """验证实际为 PNG 的图片即便保存为 .jpg 且声明为 image/jpeg，也能通过真实签名自动纠偏放行。"""
    api, session, state, client = file_api
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("web_download.jpg", PNG, "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_type"] == "image/png"
    assert data["width"] == 1 and data["height"] == 1

    row = session.scalar(select(FileObject).where(FileObject.id == int(data["id"])))
    assert row is not None
    assert row.content_type == "image/png"
    assert row.object_key.endswith(".png")


def test_upload_rejects_non_image_content(file_api):
    api, session, state, client = file_api
    response = api.post(
        "/api/v1/files",
        data={"category": "OBJECTION_PROOF"},
        files={"file": ("script.jpg", b"echo 'not an image'", "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
