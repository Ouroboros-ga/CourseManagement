import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import alibabacloud_oss_v2 as oss
import pytest
from app.modules.file.storage import LocalStorage, ObjectStorage
from tests.unit.test_oss_storage import MemoryClient, settings

path = Path(__file__).parents[1] / "production/oss_web_storage.py"
spec = importlib.util.spec_from_file_location("oss_web_storage", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_migrate_verifies_local_and_remote_without_overwriting_conflicts(tmp_path):
    local = LocalStorage(str(tmp_path), "test")
    remote = ObjectStorage(settings(), client=MemoryClient())
    body = b"test-picture"
    item = SimpleNamespace(
        object_key="a.png",
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        content_type="image/png",
    )
    local.save(item.object_key, body, item.content_type)
    assert (
        module.migrate_files([item], local, remote, apply=False)["verified_local"] == 1
    )
    assert not remote.exists(item.object_key)
    assert module.migrate_files([item], local, remote, apply=True)["copied"] == 1
    assert (
        module.migrate_files([item], local, remote, apply=True)["verified_remote"] == 1
    )
    remote.save(item.object_key, b"wrong", item.content_type)
    with pytest.raises(RuntimeError, match="remote integrity"):
        module.migrate_files([item], local, remote, apply=True)
    assert remote.read(item.object_key) == b"wrong"


def test_local_corruption_aborts_before_copy(tmp_path):
    local = LocalStorage(str(tmp_path), "test")
    remote = ObjectStorage(settings(), client=MemoryClient())
    local.save("a.png", b"corrupt", "image/png")
    item = SimpleNamespace(
        object_key="a.png", size_bytes=5, sha256="0" * 64, content_type="image/png"
    )
    with pytest.raises(RuntimeError, match="local integrity"):
        module.migrate_files([item], local, remote, apply=True)
    assert not remote.exists("a.png")


def test_csp_allows_only_exact_valid_bucket_source():
    policy = module.web_csp("https://test-course.oss-cn-shanghai.aliyuncs.com")
    assert (
        "img-src 'self' data: blob: https://test-course.oss-cn-shanghai.aliyuncs.com;"
        in policy
    )
    assert (
        "connect-src 'self' https://test-course.oss-cn-shanghai.aliyuncs.com;" in policy
    )
    for invalid in [
        "https://*.aliyuncs.com",
        "http://test-course.oss-cn-shanghai.aliyuncs.com",
        "https://evil.com; script-src *",
    ]:
        with pytest.raises(ValueError):
            module.web_csp(invalid)


def test_cors_preserves_existing_rule_and_writes_restorable_backup(tmp_path):
    existing = oss.CORSRule(
        allowed_origins=["https://existing.example"],
        allowed_methods=["GET"],
        allowed_headers=["Range"],
        expose_headers=["ETag"],
        max_age_seconds=30,
    )
    sent = []
    client = SimpleNamespace(
        get_bucket_cors=lambda request: oss.GetBucketCorsResult(
            cors_configuration=oss.CORSConfiguration(cors_rules=[existing], response_vary=False)
        )
    )
    store = SimpleNamespace(
        _client=client,
        _bucket="test-course",
        _call=lambda method, req: sent.append(req),
    )
    backup = tmp_path / "cors.json"
    module.configure_cors(store, backup, apply=True)
    assert sent[0].cors_configuration.cors_rules[0] is existing
    import json

    restored = oss.CORSRule(**json.loads(backup.read_text())["rules"][0])
    assert restored.allowed_origins == ["https://existing.example"]
    assert restored.allowed_headers == ["Range"]
