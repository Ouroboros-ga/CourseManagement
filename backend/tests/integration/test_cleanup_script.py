"""W7d 运行交付：到期清理定时脚本 deploy/scripts/cleanup_expired_files.py 端到端测试。

连真实 MySQL 测试库。脚本自身把 backend 根加入 sys.path，测试里通过 importlib 从文件
路径加载并调用 main()，验证部署入口在隔离环境可用、行为与 FileService 状态机一致：
- 退出码 0；
- 到期文件（含报表 REPORT_FILE 类别）被置 PURGED 且底层对象删除；
- 未到期文件原样保留、底层对象不受触碰；
- 逐文件独立提交、可重跑幂等（二次运行 scanned=0）。

存储目录经 FILE_LOCAL_STORAGE_DIR 指向 tmp_path，get_settings 缓存清一次再取；结束前
再清一次，避免把临时目录泄漏给同会话后续测试（monkeypatch 只自动还原 env，不清缓存）。
"""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.storage import LocalStorage
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

# backend/tests/integration/x.py -> parents[2]=backend, parents[3]=项目根；脚本在根/deploy/scripts。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "deploy" / "scripts" / "cleanup_expired_files.py"


def _load_script():
    """从文件路径加载清理脚本模块（其内部已把 backend 根加入 sys.path 供 import app）。"""
    spec = importlib.util.spec_from_file_location("cm_cleanup_script", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_file(
    session: Session,
    *,
    status: str,
    expires_in_hours: int | None,
    key: str,
    category: str,
) -> FileObject:
    now = utcnow()
    row = FileObject(
        object_key=key,
        category=category,
        original_name=f"{key}.bin",
        content_type="application/octet-stream",
        size_bytes=10,
        sha256="b" * 64,
        uploader_user_id=None,
        status=status,
        retention_policy_version=1,
        expires_at=(now + timedelta(hours=expires_in_hours))
        if expires_in_hours is not None
        else None,
    )
    session.add(row)
    session.commit()
    session.expire_all()
    return row


def test_cleanup_script_main_end_to_end(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_dir = tmp_path / "store"
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("FILE_LOCAL_STORAGE_DIR", str(store_dir))
    get_settings.cache_clear()
    try:
        store = LocalStorage(str(store_dir), secret="script-secret")

        expired = _make_file(
            session,
            status=FileStatus.READY.value,
            expires_in_hours=-1,
            key="r1",
            category=FileCategory.REPORT_FILE.value,
        )
        future = _make_file(
            session,
            status=FileStatus.READY.value,
            expires_in_hours=+24 * 400,
            key="r2",
            category=FileCategory.SUBMISSION_PHOTO.value,
        )
        store.save("r1", b"x" * 10, "application/octet-stream")
        store.save("r2", b"y" * 10, "application/octet-stream")

        rc = _load_script().main(["--batch-size", "100"])
        assert rc == 0

        # 脚本用独立连接提交，夹具会话需开新事务快照才能观察其结果。
        session.commit()
        session.expire_all()
        rexp = session.get(FileObject, int(expired.id))
        rfut = session.get(FileObject, int(future.id))
        assert rexp is not None and rfut is not None
        assert rexp.status == FileStatus.PURGED.value
        assert rexp.purged_at is not None
        assert not store.exists("r1")  # 底层对象已删
        assert rfut.status == FileStatus.READY.value
        assert store.exists("r2")  # 未到期，底层对象不受触碰

        # 重跑幂等：已 PURGED 者不再入选，第二次运行不再清理任何东西。
        rc2 = _load_script().main(["--batch-size", "100"])
        assert rc2 == 0
    finally:
        get_settings.cache_clear()
