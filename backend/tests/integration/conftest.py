"""集成测试夹具：连接隔离的 MySQL 测试库。

技术方案 27：约束/事务/并发验证必须连真实 MySQL 实例，不能靠 SQLite 通过。
若 Docker MySQL 未就绪则整套集成测试自动跳过，不影响离线单测。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_DEFAULT_TEST_DB_URL = (
    "mysql+pymysql://cm_app:change_me_app@127.0.0.1:13306/course_management_test?charset=utf8mb4"
)


def _resolve_test_db_url() -> str:
    env = os.environ.get("TEST_DATABASE_URL")
    if env:
        return env
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if dotenv_path.is_file():
        try:
            from dotenv import dotenv_values

            value = dotenv_values(str(dotenv_path)).get("TEST_DATABASE_URL")
            if value:
                return value
        except ImportError:
            pass
    return _DEFAULT_TEST_DB_URL


TEST_DB_URL = _resolve_test_db_url()


def _assert_isolated_test_db(url: str) -> None:
    """目标保护：集成夹具会 drop_all/create_all，必须落在专用测试库。

    防止误把 TEST_DATABASE_URL 指向开发业务库或生产库造成破坏性删除。
    """
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise RuntimeError(
            f"TEST_DATABASE_URL 指向的库名 '{database}' 不以 '_test' 结尾，"
            "拒绝在疑似业务/生产库上执行破坏性夹具。请改用专用测试库。"
        )


_assert_isolated_test_db(TEST_DB_URL)


def _test_engine() -> Engine:
    return create_engine(TEST_DB_URL, pool_pre_ping=True, future=True)


@pytest.fixture(scope="session")
def engine() -> Engine:
    try:
        eng = _test_engine()
        eng.connect().close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MySQL 测试库不可用，跳过集成测试：{exc}")
    return eng


@pytest.fixture(autouse=True)
def _configure_app_db(engine: Engine, monkeypatch: pytest.MonkeyPatch):
    """将应用惰性 Engine 指向测试库，并保证测试令牌密钥稳定。"""
    monkeypatch.setenv("TESTING", "1")
    # refresh Cookie 传输在测试中固定：TestClient 走明文 http://testserver，
    # 若 COOKIE_SECURE=true 则 httpx 不会把 Secure Cookie 回传到 http 源，故关之。
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("CSRF_ALLOWED_ORIGINS", "http://app.test")
    import app.core.database as dbmod
    from app.core import config as cfg

    dbmod._engine = engine
    dbmod._session_factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_schema(engine: Engine) -> None:
    from app.models import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def client(engine: Engine) -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def session(engine: Engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()
