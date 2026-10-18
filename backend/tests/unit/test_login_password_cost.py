"""Login rejection must retain Argon2 cost without creating unknown accounts."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.core.exceptions import AppError, UnauthenticatedError
from app.core.security import hash_password, verify_password
from app.modules.identity import service as identity


@pytest.mark.parametrize("password_hash", [None, "missing-user"])
def test_rejected_login_runs_real_password_verification(monkeypatch, password_hash):
    session = Mock()
    svc = identity.IdentityService(session)
    user = None if password_hash == "missing-user" else SimpleNamespace(
        password_hash=None, locked_until=None, is_active=True, failed_login_count=0
    )
    svc._repo = Mock()
    svc._repo.get_user_by_username.return_value = user
    checked = []

    def record_verification(password, encoded):
        checked.append(encoded)
        return verify_password(password, encoded)

    monkeypatch.setattr(identity, "verify_password", record_verification)
    with pytest.raises(UnauthenticatedError, match="账号或密码错误"):
        svc.login_web("unknown-fixture", "invalid-fixture-password")
    assert len(checked) == 1
    assert checked[0].startswith("$argon2id$v=19$m=65536,t=3,p=2$")
    if user is None:
        session.commit.assert_not_called()
        session.add.assert_not_called()
    else:
        assert user.failed_login_count == 1


def test_wrong_password_still_updates_existing_account_failure_count():
    session = Mock()
    svc = identity.IdentityService(session)
    user = SimpleNamespace(password_hash=hash_password("correct-fixture-password"),
                           locked_until=None, is_active=True, failed_login_count=0)
    svc._repo = Mock()
    svc._repo.get_user_by_username.return_value = user
    with pytest.raises(UnauthenticatedError):
        svc.login_web("fixture-user", "wrong-fixture-password")
    assert user.failed_login_count == 1
    session.commit.assert_called_once()


def test_locked_account_still_pays_verification_cost(monkeypatch):
    """锁定分支同样执行一次 Argon2，避免用耗时区分"已锁定"与"不存在"。"""
    from datetime import timedelta

    from app.core.database import utcnow

    checked = []
    monkeypatch.setattr(
        identity,
        "verify_password",
        lambda pw, encoded: checked.append(encoded) or False,
    )
    session = Mock()
    svc = identity.IdentityService(session)
    user = SimpleNamespace(
        password_hash=hash_password("correct-fixture-password"),
        locked_until=utcnow() + timedelta(minutes=5),
        is_active=True,
        failed_login_count=0,
    )
    svc._repo = Mock()
    svc._repo.get_user_by_username.return_value = user

    with pytest.raises(AppError) as exc:
        svc.login_web("fixture-user", "correct-fixture-password")

    assert exc.value.http_status == 429
    assert len(checked) == 1
    # 锁定期间不得用真实口令哈希做校验，否则等于继续验证口令正确性
    assert checked[0] == identity.ABSENT_ACCOUNT_PASSWORD_HASH
    assert user.failed_login_count == 0


def test_disabled_account_with_wrong_password_reports_generic_message():
    """停用账号 + 错误口令必须与"查无此人"同消息，否则消息本身即可枚举账号。"""
    session = Mock()
    svc = identity.IdentityService(session)
    user = SimpleNamespace(
        password_hash=hash_password("correct-fixture-password"),
        locked_until=None,
        is_active=False,
        failed_login_count=0,
    )
    svc._repo = Mock()
    svc._repo.get_user_by_username.return_value = user

    with pytest.raises(UnauthenticatedError, match="账号或密码错误"):
        svc.login_web("fixture-user", "wrong-fixture-password")


def test_disabled_account_with_correct_password_reports_disabled():
    """口令已通过才暴露停用状态：此时调用方已证明持有凭据，不构成枚举面。"""
    session = Mock()
    svc = identity.IdentityService(session)
    user = SimpleNamespace(
        password_hash=hash_password("correct-fixture-password"),
        locked_until=None,
        is_active=False,
        failed_login_count=0,
    )
    svc._repo = Mock()
    svc._repo.get_user_by_username.return_value = user

    with pytest.raises(UnauthenticatedError, match="账号未启用"):
        svc.login_web("fixture-user", "correct-fixture-password")
