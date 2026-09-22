"""P5 Wave 5b：文件受限上传 / 短时签名访问 / 验签下载 集成测试（连真实 MySQL 测试库）。

覆盖技术方案 16.1、16.2 与 DEVELOPMENT_PLAN P5 文件波：
- 认证：无令牌 401。
- 上传校验：真实签名 + 扩展名 + 声明 MIME 三方一致、单文件字节上限、图像像素上限、
  空内容 / 未知类别；通过则建 READY 行、固化 expires_at、写 file.upload 审计，
  并经可插拔本地存储落盘（对象键服务端随机）。
- 访问：上传者本人得短时签名链接；他人 / 未知 id 统一 404 防枚举；已过期 410 FILE_EXPIRED。
- 下载：签名有效且未过期 → 200 原字节；签名被篡改或过期 → 403；不重新鉴权（16.2）。

不依赖重型图像库：用纯字节构造 PNG / JPEG / WebP 文件头供解析器读取尺寸。
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from app.core.database import utcnow
from app.core.exceptions import ErrorCode
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileObject, FileStatus
from app.modules.identity.models import Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_FILES = "/api/v1/files"


# --------------------------------------------------------------------------- #
# 最小图像字节构造（仅需满足纯解析器的签名与尺寸读取）
# --------------------------------------------------------------------------- #
def _png(w: int, h: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">II", w, h) + bytes([8, 2, 0, 0, 0])
    chunk = struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", 0)
    return sig + chunk + b"IEND"


def _jpeg(w: int, h: int) -> bytes:
    # SOF0：FFC0 len precision H(2BE) W(2BE) ncomp + 采样占位。
    sof = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + b"\x03\x01\x11\x00"
    return b"\xff\xd8" + sof + b"\x00" * 16 + b"\xff\xd9"


def _webp(w: int, h: int) -> bytes:
    # RIFF/WEBP + VP8X（4 flags + 3B W-1 + 3B H-1），payload 10 字节。
    canvas = ((w - 1).to_bytes(3, "little")) + ((h - 1).to_bytes(3, "little"))
    vp8x = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + canvas
    body = b"WEBP" + vp8x
    return b"RIFF" + struct.pack("<I", len(body)) + body


# --------------------------------------------------------------------------- #
# 装配助手
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    sync_registry(session)
    session.commit()


def _role(session: Session, code: str) -> Role:
    return session.execute(select(Role).where(Role.code == code)).scalar_one()


def _make_user(session: Session, username: str, role_codes: list[str]) -> UserAccount:
    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [_role(session, c) for c in role_codes]
    session.add(user)
    session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": username, "password": _PWD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.fixture()
def admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


@pytest.fixture()
def storage_dir(monkeypatch: pytest.MonkeyPatch):
    """把本地存储根目录指向独立临时目录，隔离落盘并对齐 SECRET。"""
    root = tempfile.mkdtemp(prefix="cm_files_")
    monkeypatch.setenv("FILE_LOCAL_STORAGE_DIR", root)
    monkeypatch.setenv("FILE_SIGNED_URL_TTL_SECONDS", "60")
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    yield Path(root)
    cfg.get_settings.cache_clear()
    shutil.rmtree(root, ignore_errors=True)


def _upload(
    client,
    headers,
    *,
    content: bytes,
    filename: str,
    mime: str,
    category: str = "SUBMISSION_PHOTO",
):
    return client.post(
        _FILES,
        headers=headers,
        files={"file": (filename, content, mime)},
        data={"category": category},
    )


def _file_row(session: Session, file_id: int) -> FileObject:
    session.expire_all()
    return session.execute(
        select(FileObject).where(FileObject.id == file_id)
    ).scalar_one()


# --------------------------------------------------------------------------- #
# 认证
# --------------------------------------------------------------------------- #
def test_upload_requires_auth(client: TestClient, storage_dir) -> None:
    resp = client.post(
        _FILES,
        files={"file": ("a.png", _png(4, 3), "image/png")},
        data={"category": "SUBMISSION_PHOTO"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHENTICATED.value


# --------------------------------------------------------------------------- #
# 上传 happy + 落库 + 落盘 + 审计
# --------------------------------------------------------------------------- #
def test_upload_valid_png_persists_and_audits(
    client: TestClient, admin_headers, session: Session, storage_dir
) -> None:
    resp = _upload(
        client, admin_headers, content=_png(4, 3), filename="photo.png", mime="image/png"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == FileStatus.READY.value
    assert data["content_type"] == "image/png"
    assert data["width"] == 4 and data["height"] == 3
    assert data["size_bytes"] == len(_png(4, 3))
    assert len(data["sha256"]) == 64
    assert data["expires_at"] is not None  # 保留期固化

    row = _file_row(session, int(data["id"]))
    assert row.uploader_user_id is not None
    assert row.status == FileStatus.READY.value
    # 对象键服务端随机、分层，绝不用上传原名。
    assert "photo.png" not in row.object_key
    assert (storage_dir / row.object_key).exists()

    audit = session.execute(
        select(AuditLog).where(AuditLog.action == "file.upload")
    ).scalars().all()
    assert len(audit) == 1
    assert audit[0].resource_type == "file_object"


def test_upload_jpeg_and_webp_dimensions(
    client: TestClient, admin_headers, storage_dir
) -> None:
    r1 = _upload(client, admin_headers, content=_jpeg(8, 5), filename="c.jpg", mime="image/jpeg")
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["content_type"] == "image/jpeg"
    assert r1.json()["data"]["width"] == 8 and r1.json()["data"]["height"] == 5

    r2 = _upload(client, admin_headers, content=_webp(10, 7), filename="w.webp", mime="image/webp")
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["width"] == 10 and r2.json()["data"]["height"] == 7


# --------------------------------------------------------------------------- #
# 上传校验拒绝路径
# --------------------------------------------------------------------------- #
def test_upload_rejects_disallowed_extension(
    client: TestClient, admin_headers, storage_dir
) -> None:
    resp = _upload(client, admin_headers, content=_png(2, 2), filename="x.gif", mime="image/png")
    assert resp.status_code == 422
    assert "file" in resp.json()["fieldErrors"]


def test_upload_rejects_ext_signature_mismatch(
    client: TestClient, admin_headers, storage_dir
) -> None:
    # PNG 真实内容伪装成 .jpg 扩展名。
    resp = _upload(client, admin_headers, content=_png(2, 2), filename="x.jpg", mime="image/png")
    assert resp.status_code == 422


def test_upload_rejects_mime_mismatch(
    client: TestClient, admin_headers, storage_dir
) -> None:
    resp = _upload(
        client, admin_headers, content=_png(2, 2), filename="x.png", mime="image/jpeg"
    )
    assert resp.status_code == 422


def test_upload_rejects_fake_signature(
    client: TestClient, admin_headers, storage_dir
) -> None:
    resp = _upload(
        client,
        admin_headers,
        content=b"definitely not an image",
        filename="x.png",
        mime="image/png",
    )
    assert resp.status_code == 422
    assert "签名" in resp.json()["message"] or "图像" in resp.json()["message"]


def test_upload_rejects_empty(client: TestClient, admin_headers, storage_dir) -> None:
    resp = _upload(client, admin_headers, content=b"", filename="x.png", mime="image/png")
    assert resp.status_code == 422


def test_upload_rejects_oversize(
    client: TestClient, admin_headers, storage_dir, monkeypatch
) -> None:
    monkeypatch.setenv("FILE_MAX_BYTES", "16")
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    resp = _upload(
        client, admin_headers, content=_png(64, 64), filename="big.png", mime="image/png"
    )
    assert resp.status_code == 422
    cfg.get_settings.cache_clear()


def test_upload_rejects_excess_pixels(
    client: TestClient, admin_headers, storage_dir, monkeypatch
) -> None:
    monkeypatch.setenv("FILE_MAX_IMAGE_PIXELS", "100")
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    resp = _upload(
        client, admin_headers, content=_png(50, 50), filename="px.png", mime="image/png"
    )
    assert resp.status_code == 422
    assert "像素" in resp.json()["message"]
    cfg.get_settings.cache_clear()


def test_upload_rejects_unknown_category(
    client: TestClient, admin_headers, storage_dir
) -> None:
    resp = _upload(
        client,
        admin_headers,
        content=_png(2, 2),
        filename="x.png",
        mime="image/png",
        category="COOKIES",
    )
    assert resp.status_code == 422
    assert resp.json()["fieldErrors"]["category"] == "COOKIES"


# --------------------------------------------------------------------------- #
# 访问授权 + 下载
# --------------------------------------------------------------------------- #
def test_access_by_uploader_then_download_ok(
    client: TestClient, admin_headers, storage_dir
) -> None:
    blob = _png(4, 3)
    up = _upload(client, admin_headers, content=blob, filename="p.png", mime="image/png")
    fid = int(up.json()["data"]["id"])

    acc = client.get(f"{_FILES}/{fid}/access", headers=admin_headers)
    assert acc.status_code == 200, acc.text
    body = acc.json()["data"]
    assert body["method"] == "GET"
    assert body["expires_in"] == 60
    assert body["url"].startswith(f"{_FILES}/{fid}/download")

    dl = client.get(body["url"])
    assert dl.status_code == 200, dl.text
    assert dl.content == blob
    assert dl.headers["content-type"] == "image/png"


def test_access_other_user_invisible_404(
    client: TestClient, admin_headers, session: Session, storage_dir
) -> None:
    up = _upload(client, admin_headers, content=_png(4, 3), filename="p.png", mime="image/png")
    fid = int(up.json()["data"]["id"])

    _make_user(session, "bob", [RoleCode.VOLUNTEER.value])
    bob = _bearer(_login(client, "bob"))
    # bob 非上传者、文件未关联任何其可见提交 → 不可见，统一 404 防枚举。
    acc = client.get(f"{_FILES}/{fid}/access", headers=bob)
    assert acc.status_code == 404


def test_access_unknown_id_404(client: TestClient, admin_headers, storage_dir) -> None:
    acc = client.get(f"{_FILES}/999999/access", headers=admin_headers)
    assert acc.status_code == 404


def test_access_file_expired_410(
    client: TestClient, admin_headers, session: Session, storage_dir
) -> None:
    up = _upload(client, admin_headers, content=_png(4, 3), filename="p.png", mime="image/png")
    fid = int(up.json()["data"]["id"])
    row = _file_row(session, fid)
    row.expires_at = utcnow() - timedelta(days=1)
    session.commit()

    acc = client.get(f"{_FILES}/{fid}/access", headers=admin_headers)
    assert acc.status_code == 410
    assert acc.json()["code"] == ErrorCode.FILE_EXPIRED.value


def test_download_rejects_bad_signature(
    client: TestClient, admin_headers, storage_dir
) -> None:
    up = _upload(client, admin_headers, content=_png(4, 3), filename="p.png", mime="image/png")
    fid = int(up.json()["data"]["id"])
    acc = client.get(f"{_FILES}/{fid}/access", headers=admin_headers)
    good_url = acc.json()["data"]["url"]
    tampered = good_url.rsplit("sig=", 1)[0] + "sig=" + "0" * 64
    dl = client.get(tampered)
    assert dl.status_code == 403


def test_download_rejects_expired_link(
    client: TestClient, admin_headers, storage_dir
) -> None:
    up = _upload(client, admin_headers, content=_png(4, 3), filename="p.png", mime="image/png")
    fid = int(up.json()["data"]["id"])
    dl = client.get(f"{_FILES}/{fid}/download?expires=1&sig=" + "0" * 64)
    assert dl.status_code == 403
