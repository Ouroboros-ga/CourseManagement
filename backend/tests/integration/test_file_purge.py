"""文件域 P5e：到期材料清理（purge_expired_files）集成测试，连真实 MySQL 测试库。

覆盖技术方案 16.1 / 16.3 与 DEVELOPMENT_PLAN 第 65–66 条的状态机与可重跑语义：
- READY 且已到期 → 删底层对象成功 → PURGED + purged_at + 无操作者审计（file.purge）。
- 未到期 / 非到期候选（UPLOADING/FAILED/已 PURGED）不动。
- 底层删除失败 → 保留 PURGE_PENDING、计 failed、不置 PURGED、不写清理审计，留待下次。
- 底层对象已不存在（delete 返回 False）视作清理完成，仍置 PURGED（幂等）。
- 重跑幂等：已 PURGED 者不再入选候选。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.service import FileService
from app.modules.file.storage import LocalStorage
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


class _FailingStorage:
    """delete 抛错的存储替身，用于验证删除失败时不改判为已清理。"""

    def __init__(self, inner: LocalStorage) -> None:
        self._inner = inner

    def save(self, object_key: str, data: bytes, content_type: str) -> None:
        self._inner.save(object_key, data, content_type)

    def read(self, object_key: str) -> bytes:  # pragma: no cover - 未用
        return self._inner.read(object_key)

    def exists(self, object_key: str) -> bool:  # pragma: no cover - 未用
        return self._inner.exists(object_key)

    def presign_get(self, file_id: int, object_key: str, ttl_seconds: int) -> str:
        return self._inner.presign_get(file_id, object_key, ttl_seconds)

    def delete(self, object_key: str) -> bool:
        raise RuntimeError("底层删除故障")


def _make_file(
    session: Session,
    *,
    status: str,
    expires_in_hours: int | None,
    key: str,
    category: str = FileCategory.SUBMISSION_PHOTO.value,
    content_type: str = "image/png",
    ext: str = "png",
) -> FileObject:
    now = utcnow()
    row = FileObject(
        object_key=key,
        category=category,
        original_name=f"{key}.{ext}",
        content_type=content_type,
        size_bytes=10,
        sha256="a" * 64,
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


def _reload(session: Session, file_id: int) -> FileObject:
    session.commit()
    session.expire_all()
    row = session.get(FileObject, file_id)
    assert row is not None
    return row


def _purge_audits(session: Session) -> list[AuditLog]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(AuditLog).where(AuditLog.action == "file.purge")
        ).scalars().all()
    )


def _storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(str(tmp_path / "store"), secret="test-secret")


def test_purge_expired_ready_marks_purged_and_audits(
    session: Session, tmp_path: Path
) -> None:
    store = _storage(tmp_path)
    row = _make_file(
        session, status=FileStatus.READY.value, expires_in_hours=-1, key="exp1"
    )
    store.save("exp1", b"x" * 10, "image/png")
    assert store.exists("exp1")

    stats = FileService(session, storage=store).purge_expired_files()
    assert stats["purged"] == 1
    assert stats["failed"] == 0
    after = _reload(session, row.id)
    assert after.status == FileStatus.PURGED.value
    assert after.purged_at is not None
    assert not store.exists("exp1")  # 底层对象已删

    audits = _purge_audits(session)
    assert len(audits) == 1
    assert audits[0].actor_user_id is None  # 系统触发无操作者
    assert audits[0].resource_id == str(row.id)
    assert audits[0].reason == "retention_expired"


def test_purge_skips_not_expired_and_other_states(
    session: Session, tmp_path: Path
) -> None:
    store = _storage(tmp_path)
    future = _make_file(
        session, status=FileStatus.READY.value, expires_in_hours=+24, key="fut"
    )
    uploading = _make_file(
        session, status=FileStatus.UPLOADING.value, expires_in_hours=-1, key="upl"
    )
    stats = FileService(session, storage=store).purge_expired_files()
    assert stats["scanned"] == 0
    assert stats["purged"] == 0
    assert _reload(session, future.id).status == FileStatus.READY.value
    assert _reload(session, uploading.id).status == FileStatus.UPLOADING.value


def test_purge_missing_object_still_purges(session: Session, tmp_path: Path) -> None:
    # 库里 READY 已到期但底层对象缺失（delete 返回 False）：视作清理完成，仍置 PURGED。
    store = _storage(tmp_path)
    row = _make_file(
        session, status=FileStatus.READY.value, expires_in_hours=-1, key="gone"
    )
    stats = FileService(session, storage=store).purge_expired_files()
    assert stats["purged"] == 1
    assert _reload(session, row.id).status == FileStatus.PURGED.value


def test_purge_delete_failure_keeps_pending(
    session: Session, tmp_path: Path
) -> None:
    inner = _storage(tmp_path)
    inner.save("bad", b"x", "image/png")
    failing: Any = _FailingStorage(inner)
    row = _make_file(
        session, status=FileStatus.READY.value, expires_in_hours=-1, key="bad"
    )

    stats = FileService(session, storage=failing).purge_expired_files()
    assert stats["marked"] == 1
    assert stats["failed"] == 1
    assert stats["purged"] == 0
    # 关键：删除失败绝不改判为已清理——停在 PURGE_PENDING 待下次运行。
    after = _reload(session, row.id)
    assert after.status == FileStatus.PURGE_PENDING.value
    assert after.purged_at is None
    assert _purge_audits(session) == []


def test_purge_rerun_is_idempotent(session: Session, tmp_path: Path) -> None:
    store = _storage(tmp_path)
    _make_file(session, status=FileStatus.READY.value, expires_in_hours=-1, key="once")
    svc = FileService(session, storage=store)
    first = svc.purge_expired_files()
    assert first["purged"] == 1
    # 再次运行：已 PURGED 者不再是候选，无重复清理、无重复审计。
    second = svc.purge_expired_files()
    assert second["scanned"] == 0
    assert second["purged"] == 0
    assert len(_purge_audits(session)) == 1


# --------------------------------------------------------------------------- #
# W7d 运行交付：报表产物（REPORT_FILE）纳入清理但走自有归档期限
# --------------------------------------------------------------------------- #
def test_report_file_expired_is_purged_but_future_survives(
    session: Session, tmp_path: Path
) -> None:
    """REPORT_FILE 与照片/临时件共用按 expires_at 固化的清理状态机。

    报表产物在建时按自有归档期限（FILE_RETENTION_REPORT_FILE_DAYS）固化到期时刻：
    未到期者绝不被清理误删；确已到期者按同一状态机置 PURGED。二者同批处理，证明
    "清理类别无关、期限各自固化"（技术方案 16.3、DEVELOPMENT_PLAN 第 65 条）。
    """
    store = _storage(tmp_path)
    expired = _make_file(
        session,
        status=FileStatus.READY.value,
        expires_in_hours=-1,  # 已过归档期
        key="report-expired",
        category=FileCategory.REPORT_FILE.value,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ext="xlsx",
    )
    future = _make_file(
        session,
        status=FileStatus.READY.value,
        expires_in_hours=+24 * 400,  # 模拟 365 天归档期，远未到期
        key="report-future",
        category=FileCategory.REPORT_FILE.value,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ext="xlsx",
    )
    store.save("report-expired", b"x" * 10, "application/octet-stream")
    store.save("report-future", b"y" * 10, "application/octet-stream")

    stats = FileService(session, storage=store).purge_expired_files()
    # 仅到期那份入选并清理，未到期那份原样保留。
    assert stats["scanned"] == 1
    assert stats["purged"] == 1
    assert _reload(session, expired.id).status == FileStatus.PURGED.value
    assert not store.exists("report-expired")
    assert _reload(session, future.id).status == FileStatus.READY.value
    assert store.exists("report-future")  # 归档期内，底层对象不受触碰


def test_report_retention_days_are_configurable_and_independent() -> None:
    """报表保留天数走 Settings/env（冻结纪律），且与临时件期限相互独立。"""
    settings = get_settings()
    mapping = settings.file_retention_days_by_category()
    assert "REPORT_FILE" in mapping
    assert mapping["REPORT_FILE"] == settings.file_retention_report_file_days
    # 独立归档期限：不套用 TEMP 短周期，二者各由独立 env 驱动。
    assert mapping["TEMP"] == settings.file_retention_temp_days
    assert mapping["REPORT_FILE"] != mapping["TEMP"]
