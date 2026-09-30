"""审计读取仅暴露安全字段，时间范围有限。"""

from datetime import UTC, datetime, timedelta

import pytest
from app.modules.audit.schemas import safe_snapshot, validate_window


def test_audit_snapshot_drops_secrets_and_unknown_fields() -> None:
    source = {
        "status": "ACTIVE",
        "lock_version": 2,
        "password_hash": "secret",
        "refresh_token": "secret",
        "proof_text": "medical details",
        "student_id": 9,
        "nested": {"token": "secret"},
    }
    assert safe_snapshot(source) == {"status": "ACTIVE", "lock_version": 2, "student_id": "9"}


def test_audit_window_rejects_over_31_days() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="31"):
        validate_window(start, start + timedelta(days=31, seconds=1))
    validate_window(start, start + timedelta(days=31))


def test_audit_window_accepts_mixed_utc_input_styles() -> None:
    validate_window(datetime(2026, 9, 1), datetime(2026, 9, 2, tzinfo=UTC))
