"""迁移落地验证（开发路线 P1 第 3 步）——必须连真实 MySQL。

覆盖三件事，弥补"现有集成夹具只 create_all、不测迁移"的空白：
1. 旧结构升级：从初始迁移出发，在缺少 lock_version/audit_log 的旧库上升级
   到 head 后两样对象确实出现，且既有账号行的 lock_version 回填为 0。
2. 可逆性：downgrade 回初始结构后 audit_log 与 lock_version 被移除。
3. metadata 一致性：升到 head 后与 ORM 目标比对无漂移，并保证单一 head。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import autogenerate, command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.models import Base
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import sessionmaker

from tests.integration.conftest import TEST_DB_URL

_BACKEND = Path(__file__).resolve().parents[2]
_INITIAL_REV = "2179f23fabd2"

pytestmark = pytest.mark.integration


def _make_cfg() -> Config:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "migrations"))
    return cfg


@contextmanager
def _alembic_on_test_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    """让 env.py 读取到的 database_url 指向隔离测试库，返回可用 Config。"""
    from app.core import config as appcfg

    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    appcfg.get_settings.cache_clear()
    try:
        yield _make_cfg()
    finally:
        appcfg.get_settings.cache_clear()


def test_alembic_has_single_head() -> None:
    script = ScriptDirectory.from_config(_make_cfg())
    heads = script.get_heads()
    assert len(heads) == 1, f"期望单一迁移 head，实际：{heads}"


def test_upgrade_from_initial_then_downgrade(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 清空夹具 create_all 留下的表，并移除 Alembic 记账表，得到真正空库再按迁移重建。
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS `alembic_version`"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with _alembic_on_test_db(monkeypatch) as cfg:
        # 1) 先升级到初始结构（无 lock_version / audit_log）。
        command.upgrade(cfg, _INITIAL_REV)
        insp = inspect(engine)
        assert "audit_log" not in insp.get_table_names()
        assert "lock_version" not in {c["name"] for c in insp.get_columns("user_account")}

        # 在旧结构上插入一条账号行，验证升级后回填默认值。
        with factory() as s:
            s.execute(
                text(
                    "INSERT INTO user_account (username, display_name, status,"
                    " failed_login_count, created_at, updated_at)"
                    " VALUES ('mig_probe', '探测', 'ACTIVE', 0, NOW(3), NOW(3))"
                )
            )
            s.commit()

        # 2) 升级到 head。
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        assert "audit_log" in insp.get_table_names()
        cols = {c["name"]: c for c in insp.get_columns("user_account")}
        assert "lock_version" in cols
        assert cols["lock_version"]["nullable"] is False
        idx = {i["name"] for i in insp.get_indexes("audit_log")}
        assert "ix_audit_log_actor_user_id" in idx

        with factory() as s:
            val = s.execute(
                text("SELECT lock_version FROM user_account WHERE username='mig_probe'")
            ).scalar_one()
            assert val == 0

        # 3) metadata 一致性：升到头后与 ORM 目标比对无漂移。
        _assert_no_metadata_drift(engine)

        # 4) 可逆：回退到初始结构后新增对象消失。
        command.downgrade(cfg, _INITIAL_REV)
        insp = inspect(engine)
        assert "audit_log" not in insp.get_table_names()
        assert "lock_version" not in {c["name"] for c in insp.get_columns("user_account")}


def _assert_no_metadata_drift(engine: Engine) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "target_metadata": Base.metadata,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        diff = autogenerate.compare_metadata(ctx, Base.metadata)
        assert diff == [], f"迁移与 ORM 目标存在漂移：{diff}"
