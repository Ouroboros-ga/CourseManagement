"""OSS 边界测试：模拟 SDK 网络边界，不访问真实桶。"""

import io
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import alibabacloud_oss_v2 as oss
import pytest
from app.core.config import Settings
from app.core.database import utcnow
from app.core.exceptions import PermissionDeniedError
from app.modules.file.models import FileObject
from app.modules.file.service import FileService
from app.modules.file.storage import ObjectStorage
from pydantic import ValidationError


def settings(**overrides):
    return Settings(
        _env_file=None,
        FILE_STORAGE_BACKEND="object",
        OSS_BUCKET="test-course",
        OSS_REGION="cn-shanghai",
        OSS_ENDPOINT="https://oss-cn-shanghai.aliyuncs.com",
        SECRET_KEY="unit-test-only-secret",
        **overrides,
    )


class MemoryClient:
    def __init__(self):
        self.objects = {}

    def put_object(self, request):
        self.objects[request.key] = (request.body, request.content_type)

    def get_object(self, request):
        return SimpleNamespace(body=io.BytesIO(self.objects[request.key][0]))

    def delete_object(self, request):
        self.objects.pop(request.key, None)

    def is_object_exist(self, bucket, key):
        return key in self.objects


def test_oss_roundtrip_and_idempotent_delete():
    client = MemoryClient()
    storage = ObjectStorage(settings(), client=client)
    storage.save("2026/10/random.png", b"image", "image/png")
    assert storage.exists("2026/10/random.png")
    assert storage.read("2026/10/random.png") == b"image"
    assert client.objects["2026/10/random.png"][1] == "image/png"
    assert storage.delete("2026/10/random.png")
    assert not storage.exists("2026/10/random.png")
    assert storage.delete("2026/10/random.png")  # OSS DeleteObject is idempotent


def test_oss_access_url_uses_application_signature():
    storage = ObjectStorage(settings(), client=MemoryClient())
    url = storage.presign_get(123, "2026/10/random.png", 300)
    parts = urlsplit(url)
    assert parts.path == "/api/v1/files/123/download"
    query = parse_qs(parts.query)
    expires, sig = int(query["expires"][0]), query["sig"][0]
    assert storage.verify_download("2026/10/random.png", expires, sig)
    assert not storage.verify_download("different.png", expires, sig)
    assert not storage.verify_download("2026/10/random.png", 0, sig)
    assert not storage.verify_download("2026/10/random.png", expires, "forged")


def test_object_configuration_required():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, FILE_STORAGE_BACKEND="object")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://oss-cn-shanghai.aliyuncs.com",
        "https://example.com",
        "https://oss-cn-beijing.aliyuncs.com",
    ],
)
def test_invalid_endpoint_rejected(endpoint):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            FILE_STORAGE_BACKEND="object",
            OSS_BUCKET="test-course",
            OSS_REGION="cn-shanghai",
            OSS_ENDPOINT=endpoint,
        )


def test_missing_verifier_never_allows_download():
    service = FileService.__new__(FileService)
    service._storage = SimpleNamespace(read=Mock(return_value=b"private"))
    service._repo = Mock()
    service._repo.get.return_value = FileObject(
        id=1,
        object_key="private.png",
        category="TEMP",
        status="READY",
        expires_at=utcnow() + timedelta(days=1),
    )
    with pytest.raises(PermissionDeniedError):
        service.download(1, 9999999999, "forged")
    service._storage.read.assert_not_called()


def test_real_sdk_existence_signature_and_missing_object_mapping():
    cfg = oss.config.load_default()
    cfg.region = "cn-shanghai"
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider("fake", "fake")
    client = oss.Client(cfg)
    client.get_object_meta = Mock(return_value=SimpleNamespace(status_code=200))
    storage = ObjectStorage(settings(), client=client)
    assert storage.exists("present.png")
    request = client.get_object_meta.call_args.args[0]
    assert request.bucket == "test-course"
    assert request.key == "present.png"
    missing = oss.exceptions.OperationError(
        error=oss.exceptions.ServiceError(
            status_code=404,
            code="NoSuchKey",
            message="missing",
            request_id="test",
            ec="test",
            timestamp="test",
            request_target="test",
        ),
        name="get_object",
    )
    client.get_object = Mock(side_effect=missing)
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        storage.read("missing.png")


def test_storage_failure_is_sanitized():
    from app.core.exceptions import AppError

    client = MemoryClient()
    client.put_object = Mock(side_effect=RuntimeError("secret-token-signed-url"))
    storage = ObjectStorage(settings(), client=client)
    with pytest.raises(AppError) as caught:
        storage.save("a.png", b"image", "image/png")
    assert caught.value.http_status == 503
    assert "secret" not in str(caught.value)
