"""安全基线：响应头、生产环境信息收敛、接口定义不暴露。

这些断言对应上线前审计的 P1-1（安全头）、P2-2（健康检查信息泄漏）与
"生产仍暴露 /openapi.json" 的回归点，避免修复被后续重构悄悄改回去。
"""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.main import create_app
from fastapi.testclient import TestClient

_HEADER_EXPECTATIONS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@pytest.fixture
def dev_app(monkeypatch):
    """固定为 dev：避免 .env 或 CI 环境变量让断言随环境漂移。"""
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


@pytest.fixture
def prod_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


def test_baseline_headers_present(dev_app) -> None:
    resp = TestClient(dev_app).get("/health/live")
    for name, expected in _HEADER_EXPECTATIONS.items():
        assert resp.headers.get(name) == expected, name
    assert "geolocation=()" in resp.headers["Permissions-Policy"]
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


def test_hsts_scoped_to_production(dev_app, prod_app) -> None:
    """本地 http 下发 HSTS 会让浏览器把域名锁成 HTTPS，调试环境必须排除。"""
    assert "Strict-Transport-Security" not in TestClient(dev_app).get("/health/live").headers
    prod_hsts = TestClient(prod_app).get("/health/live").headers["Strict-Transport-Security"]
    assert prod_hsts == "max-age=31536000; includeSubDomains"


def test_production_health_hides_infrastructure_details(prod_app) -> None:
    body = TestClient(prod_app).get("/health/live").json()
    assert body["status"] == "ok"
    assert "env" not in body
    assert "database" not in body


def test_non_production_keeps_diagnostics(dev_app) -> None:
    body = TestClient(dev_app).get("/health/live").json()
    assert body["env"] == "dev"


def test_production_disables_docs_and_schema(prod_app) -> None:
    """只关 docs_url 时 /openapi.json 仍可读，两条路由必须同时关闭。"""
    client = TestClient(prod_app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_development_keeps_docs_and_relaxes_csp(dev_app) -> None:
    resp = TestClient(dev_app).get("/docs")
    assert resp.status_code == 200
    # Swagger UI 依赖 CDN 脚本，严格 CSP 会让页面白屏
    assert "Content-Security-Policy" not in resp.headers


def test_production_error_responses_carry_csp(prod_app) -> None:
    """生产连 404 也应带 CSP，避免漏掉非业务路由。"""
    resp = TestClient(prod_app).get("/no-such-route-in-production")
    assert resp.status_code == 404
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
