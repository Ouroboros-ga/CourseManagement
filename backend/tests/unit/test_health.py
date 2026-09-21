"""应用级冒烟测试：健康检查与统一错误响应。

/health/live 不依赖数据库，可在离线环境验证；/health/ready 需真实 MySQL，
其成功路径放在集成测试（tests/integration/test_health.py）中，避免离线单测
因连接超时变慢。约束/锁/事务/并发测试须连接隔离 MySQL（见技术方案 27 节）。
"""

from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient


def test_health_live_ok_without_db() -> None:
    """存活检查不触碰数据库，返回 ok 且带 X-Request-Id 关联头。"""
    client = TestClient(app)
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["check"] == "live"
    assert resp.headers.get("X-Request-Id")


def test_404_returns_error_envelope() -> None:
    client = TestClient(app)
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
