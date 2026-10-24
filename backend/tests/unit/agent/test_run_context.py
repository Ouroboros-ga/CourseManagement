from datetime import timedelta
from hashlib import sha256

import pytest
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.modules.agent.run_context import AppConnection, RunService
from app.modules.identity.models import AuthSession, Role, UserAccount, UserRole
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def session_for(db, user):
    role = db.query(Role).filter_by(code="STUDENT").first()
    if role is None:
        role = Role(code="STUDENT", name="Student")
        db.add(role)
        db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    auth = AuthSession(
        user_id=user.id,
        client_type="WECHAT",
        refresh_token_hash="0" * 64,
        refresh_family_id=f"family-{user.id}",
        expires_at=utcnow() + timedelta(days=1),
    )
    db.add(auth)
    db.commit()
    return auth


def connection(name="self-app", key="a" * 40):
    return AppConnection(
        app_key_id=name,
        key_digest=sha256(key.encode()).hexdigest(),
        entry_kind="SELF_SERVICE",
        environment="dev",
    )


def test_issued_run_stores_no_plain_token_and_resolves_real_session(campus):
    db, user = campus[1], campus[3]
    auth = session_for(db, user)
    service = RunService(db, [connection()], environment="dev")
    run, token = service.issue("self-app", user.id, auth.id)
    assert run.credential_digest != token
    assert run.credential_digest == sha256(token.encode()).hexdigest()
    context = service.resolve("a" * 40, token)
    assert context.actor.id == user.id
    assert context.run_id == str(run.id)
    with pytest.raises(AppError):
        service.resolve("a" * 40, str(run.id))


@pytest.mark.parametrize("change", ["expire", "revoke", "logout", "disable", "wrong_app"])
def test_stale_or_wrong_identity_never_restores_actor(campus, change):
    db, user = campus[1], campus[3]
    auth = session_for(db, user)
    service = RunService(db, [connection(), connection("other", "b" * 40)], environment="dev")
    run, token = service.issue("self-app", user.id, auth.id)
    key = "a" * 40
    if change == "expire":
        run.credential_expires_at = utcnow() - timedelta(seconds=1)
    elif change == "revoke":
        run.revoked_at = utcnow()
    elif change == "logout":
        auth.revoked_at = utcnow()
    elif change == "disable":
        db.get(UserAccount, user.id).status = "DISABLED"
    else:
        key = "b" * 40
    db.commit()
    with pytest.raises(AppError):
        service.resolve(key, token)


def test_token_rotation_invalidates_previous_value(campus):
    db, user = campus[1], campus[3]
    auth = session_for(db, user)
    service = RunService(db, [connection()], environment="dev")
    run, old = service.issue("self-app", user.id, auth.id)
    new = service.rotate(run.id, user.id, auth.id)
    with pytest.raises(AppError):
        service.resolve("a" * 40, old)
    assert service.resolve("a" * 40, new).actor.id == user.id


def test_session_from_another_user_cannot_issue_a_run(campus):
    db = campus[1]
    auth = session_for(db, campus[3])
    with pytest.raises(AppError):
        RunService(db, [connection()], environment="dev").issue("self-app", campus[2].id, auth.id)
