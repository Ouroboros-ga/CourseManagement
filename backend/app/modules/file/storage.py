"""文件存储后端抽象（技术方案 16.1、16.2）。

业务与权限只依赖 `StorageBackend` 协议；dev/test 无对象存储时用本地文件适配器实现，
生产可切对象存储适配器而不改文件模型与鉴权（技术方案 16.1"减少直传协议复杂度，后续可
改为短时受限直传凭证 + 服务端完成核验，业务权限和文件模型保持不变"）。

访问链接（技术方案 16.2）：存储桶关闭公共读取，对外只给服务端签发的短时签名链接；
本地适配器把对象存在受限目录（不在静态暴露路径下），签名链接指向鉴权外的下载路由，
按 §16.2"不实现每次实际下载重新鉴权、不即时撤销已发出链接"——故下载路由只校验 HMAC
签名与过期时间戳，不再查业务权限。签名用应用 SECRET_KEY，绝不外泄密钥本身。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import tempfile
from datetime import UTC, datetime
from typing import Protocol

from app.core.config import Settings


class StorageBackend(Protocol):
    """对象存储后端协议：落盘 / 读取 / 删除 / 生成短时访问 URL。"""

    def save(self, object_key: str, data: bytes, content_type: str) -> None: ...

    def read(self, object_key: str) -> bytes: ...

    def delete(self, object_key: str) -> bool: ...

    def exists(self, object_key: str) -> bool: ...

    def presign_get(self, file_id: int, object_key: str, ttl_seconds: int) -> str: ...


def _safe_relpath(object_key: str) -> str:
    """对象键按 / 分层，禁止越出根目录（防目录穿越）。"""
    parts = [p for p in object_key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return os.path.join(*parts)


class LocalStorage:
    """本地文件适配器（dev/test）。对象键映射到受限根目录下的分层文件。"""

    def __init__(self, root: str, secret: str) -> None:
        self._root = os.path.abspath(root)
        self._secret = secret.encode()

    def _path(self, object_key: str) -> str:
        return os.path.join(self._root, _safe_relpath(object_key))

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        dest = self._path(object_key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # 先写临时文件再原子替换，避免半写对象被误判为 READY。
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            shutil.move(tmp, dest)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def read(self, object_key: str) -> bytes:
        with open(self._path(object_key), "rb") as fh:
            return fh.read()

    def delete(self, object_key: str) -> bool:
        path = self._path(object_key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def exists(self, object_key: str) -> bool:
        return os.path.exists(self._path(object_key))

    def _sign(self, object_key: str, expires_epoch: int) -> str:
        msg = f"{object_key}:{expires_epoch}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def presign_get(self, file_id: int, object_key: str, ttl_seconds: int) -> str:
        expires_epoch = int(datetime.now(UTC).timestamp()) + max(ttl_seconds, 1)
        sig = self._sign(object_key, expires_epoch)
        return (
            f"/api/v1/files/{file_id}/download"
            f"?expires={expires_epoch}&sig={sig}"
        )

    def verify_download(self, object_key: str, expires_epoch: int, sig: str) -> bool:
        """下载路由校验：签名正确且未过期（技术方案 16.2：到期前可复用，不即时撤销）。"""
        if int(datetime.now(UTC).timestamp()) > expires_epoch:
            return False
        expected = self._sign(object_key, expires_epoch)
        return hmac.compare_digest(expected, sig)


class ObjectStorage:
    """对象存储适配器占位（生产接入 COS/OSS 时实现）。

    保持接口不变即可替换本地适配器；V1.0 测试与本地开发不依赖真实对象存储，故未落地
    具体 SDK，调用即显式报错提示需配置凭据与实现，避免静默退化到不安全路径。
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "对象存储适配器尚未接入：设置 FILE_STORAGE_BACKEND=local 使用本地存储，"
            "或在生产部署补全本适配器（save/read/delete/presign_get）。"
        )


def build_default_storage(settings: Settings) -> StorageBackend:
    """按配置选择存储后端。"""
    if settings.file_storage_backend == "object":
        return ObjectStorage()  # type: ignore[return-value]
    return LocalStorage(settings.file_local_storage_dir, settings.secret_key)


__all__ = [
    "StorageBackend",
    "LocalStorage",
    "ObjectStorage",
    "build_default_storage",
]
