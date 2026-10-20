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
from functools import lru_cache
from threading import Lock
from typing import Protocol

from app.core.config import Settings


class StorageBackend(Protocol):
    """对象存储后端协议：落盘 / 读取 / 删除 / 生成短时访问 URL。"""

    def save(self, object_key: str, data: bytes, content_type: str) -> None: ...

    def read(self, object_key: str) -> bytes: ...

    def delete(self, object_key: str) -> bool: ...

    def exists(self, object_key: str) -> bool: ...

    def presign_get(self, file_id: int, object_key: str, ttl_seconds: int) -> str: ...

    def verify_download(self, object_key: str, expires_epoch: int, sig: str) -> bool: ...


def _safe_relpath(object_key: str) -> str:
    """对象键按 / 分层，禁止越出根目录（防目录穿越）。"""
    parts = [p for p in object_key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return os.path.join(*parts)


class SignedDownload:
    """所有后端共用应用下载签名；OSS 凭据和桶地址不下发客户端。"""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def _sign(self, object_key: str, expires_epoch: int) -> str:
        msg = f"{object_key}:{expires_epoch}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def presign_get(self, file_id: int, object_key: str, ttl_seconds: int) -> str:
        expires_epoch = int(datetime.now(UTC).timestamp()) + max(ttl_seconds, 1)
        sig = self._sign(object_key, expires_epoch)
        return f"/api/v1/files/{file_id}/download?expires={expires_epoch}&sig={sig}"

    def verify_download(self, object_key: str, expires_epoch: int, sig: str) -> bool:
        """下载路由校验：签名正确且未过期（技术方案 16.2：到期前可复用，不即时撤销）。"""
        if int(datetime.now(UTC).timestamp()) >= expires_epoch:
            return False
        expected = self._sign(object_key, expires_epoch)
        return hmac.compare_digest(expected, sig)


class LocalStorage(SignedDownload):
    """本地文件适配器。对象键映射到受限目录下的分层文件。"""

    def __init__(self, root: str, secret: str) -> None:
        super().__init__(secret)
        self._root = os.path.abspath(root)

    def _path(self, object_key: str) -> str:
        return os.path.join(self._root, _safe_relpath(object_key))

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        dest = self._path(object_key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
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


@lru_cache(maxsize=8)
def _oss_client(region: str, endpoint: str, role_name: str, timeout: float,
                access_key_id: str = "", access_key_secret: str = ""):
    import alibabacloud_oss_v2 as oss

    lock = Lock()
    if access_key_id and access_key_secret:
        # 方案 A：跨云部署使用受限 RAM 子账号静态凭据（长时效，不开 STS 刷新）。
        def load_credentials():
            with lock:
                return oss.credentials.Credentials(
                    access_key_id, access_key_secret, None
                )
    else:
        from alibabacloud_credentials.client import Client
        from alibabacloud_credentials.models import Config

        credentials = Client(Config(type="ecs_ram_role", role_name=role_name or None))

        def load_credentials():
            # 凭据库自动刷新 STS；多请求共享客户端时串行化凭据刷新。
            with lock:
                value = credentials.get_credential()
                return oss.credentials.Credentials(
                    value.access_key_id, value.access_key_secret, value.security_token
                )
        # 凭据库自动刷新 STS；多请求共享客户端时串行化凭据刷新。
        with lock:
            value = credentials.get_credential()
            return oss.credentials.Credentials(
                value.access_key_id, value.access_key_secret, value.security_token
            )

    cfg = oss.config.load_default()
    cfg.region = region
    cfg.endpoint = endpoint
    cfg.connect_timeout = timeout
    cfg.readwrite_timeout = timeout
    cfg.retry_max_attempts = 2
    cfg.credentials_provider = oss.credentials.CredentialsProviderFunc(load_credentials)
    return oss.Client(cfg)


class ObjectStorage(SignedDownload):
    """阿里云 OSS：ECS RAM 临时凭据，下载仍由应用验签代理。"""

    def __init__(self, settings: Settings, *, client=None) -> None:
        super().__init__(settings.secret_key)
        self._bucket = settings.oss_bucket
        self._client = (
            client
            if client is not None
            else _oss_client(
                settings.oss_region,
                settings.oss_endpoint,
                settings.oss_role_name,
                settings.oss_timeout_seconds,
                settings.oss_access_key_id,
                settings.oss_access_key_secret,
            )
        )

    def _call(self, method: str, *args, **kwargs):
        from app.core.exceptions import AppError, ErrorCode, NotFoundError

        try:
            return getattr(self._client, method)(*args, **kwargs)
        except Exception as exc:
            # SDK 异常可能包含请求地址、签名和凭据，不直接进入响应或应用日志。
            unwrap = getattr(exc, "unwrap", None)
            error = unwrap() if callable(unwrap) else exc
            if getattr(error, "code", None) == "NoSuchKey":
                raise NotFoundError("文件不存在") from None
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "文件存储暂不可用，请稍后重试", http_status=503
            ) from None

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        import alibabacloud_oss_v2 as oss

        self._call(
            "put_object",
            oss.PutObjectRequest(
                bucket=self._bucket,
                key=object_key,
                body=data,
                content_type=content_type,
            ),
        )

    def read(self, object_key: str) -> bytes:
        import alibabacloud_oss_v2 as oss

        from app.core.exceptions import AppError, ErrorCode

        result = self._call("get_object", oss.GetObjectRequest(bucket=self._bucket, key=object_key))
        try:
            with result.body as body:
                return body.read()
        except Exception:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE, "文件读取失败，请稍后重试", http_status=503
            ) from None

    def delete(self, object_key: str) -> bool:
        import alibabacloud_oss_v2 as oss

        self._call("delete_object", oss.DeleteObjectRequest(bucket=self._bucket, key=object_key))
        return True  # OSS 对已不存在对象的删除也返回成功。

    def exists(self, object_key: str) -> bool:
        return bool(self._call("is_object_exist", bucket=self._bucket, key=object_key))


def build_default_storage(settings: Settings) -> StorageBackend:
    """按配置选择存储后端。"""
    if settings.file_storage_backend == "object":
        return ObjectStorage(settings)
    return LocalStorage(settings.file_local_storage_dir, settings.secret_key)


__all__ = [
    "StorageBackend",
    "LocalStorage",
    "ObjectStorage",
    "build_default_storage",
]
