"""健康检查就绪端点集成测试（连真实 MySQL 测试库）。

验证 /health/ready 在数据库可用时返回 200 且 database=up。
MySQL 不可用时由 conftest 的 engine 夹具整体跳过。
"""

from __future__ import annotations

import app.core.database as dbmod
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration


def test_health_ready_ok_when_db_up(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 让健康检查复用测试库引擎，避免探测到默认开发库。
    monkeypatch.setattr(dbmod, "_engine", engine)
    resp = client.get("/health/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["check"] == "ready"
    assert body["database"] == "up"
