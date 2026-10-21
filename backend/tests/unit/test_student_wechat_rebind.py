"""学生业务UID不随微信换绑变化；虚构档案及内存数据库。"""

from datetime import date, timedelta

import pytest
from app.core.database import utcnow
from app.core.exceptions import ConflictError, UnauthenticatedError
from app.core.security import hash_token
from app.modules.academic.models import Student
from app.modules.identity.models import (
    AuthSession,
    IdentityBindingToken,
    Permission,
    Role,
    RolePermission,
    UserAccount,
    WechatIdentity,
)
from app.modules.identity.service import IdentityService
from app.modules.inspection.models import InspectionAssignment, InspectionSubmission, InspectionTask
from sqlalchemy import select

from tests.unit.test_staff_management import staff_env as staff_env_fixture


@pytest.fixture
def env():
    for value in staff_env_fixture.__wrapped__():
        db = value["db"]
        permission = Permission(code="identity.binding.manage", name="绑定管理")
        db.add(permission)
        db.flush()
        db.add(
            RolePermission(
                role_id=db.scalar(select(Role.id).where(Role.code == "SUPER_ADMIN")),
                permission_id=permission.id,
            )
        )
        db.commit()
        yield value


def seed(env):
    db = env["db"]
    a = Student(student_no="00001", name="学生A", administrative_class_id=1)
    b = Student(student_no="00002", name="学生B", administrative_class_id=1)
    db.add_all([a, b])
    db.flush()
    owner = UserAccount(student_id=b.id, display_name=b.name, status="ACTIVE")
    other = UserAccount(display_name="微信B", status="ACTIVE")
    db.add_all([owner, other])
    db.flush()
    service = IdentityService(db)
    for role in ["STUDENT", "VOLUNTEER"]:
        obj = service._repo.get_or_create_role(role, role)
        service._repo.grant_role(owner.id, obj.id)
    wx_a = WechatIdentity(user_id=owner.id, appid="test", openid="wx-a")
    wx_b = WechatIdentity(user_id=other.id, appid="test", openid="wx-b")
    db.add_all([wx_a, wx_b])
    session = AuthSession(
        user_id=owner.id,
        client_type="WECHAT",
        refresh_token_hash=hash_token("refresh-a"),
        refresh_family_id="family-a",
        expires_at=utcnow() + timedelta(days=1),
    )
    db.add(session)
    tasks = []
    for idx in [1, 2]:
        task = InspectionTask(
            college_id=1,
            task_key=f"test-{idx}",
            semester_id=1,
            inspection_date=date(2026, 10, 21),
            week_no=1,
            inspection_type="COURSE",
            start_period=1,
            end_period=1,
        )
        db.add(task)
        db.flush()
        tasks.append(task)
        db.add(
            InspectionAssignment(
                task_id=task.id, volunteer_user_id=owner.id, assign_method="MANUAL"
            )
        )
    db.add(
        InspectionSubmission(
            task_id=tasks[1].id,
            volunteer_user_id=owner.id,
            attempt_no=1,
            roster_version=1,
            result="NORMAL",
            review_status="APPROVED",
            submitted_at=utcnow(),
        )
    )
    db.commit()
    return a, b, owner, other, wx_a, wx_b, session


def code(db, student, text):
    db.add(
        IdentityBindingToken(
            student_id=student.id,
            token_hash=hash_token(text),
            status="UNUSED",
            expires_at=utcnow() + timedelta(days=1),
        )
    )
    db.commit()


def test_unbind_keeps_student_business_uid_and_role(env):
    _, b, owner, _, wx_a, _, old_session = seed(env)
    IdentityService(env["db"]).student_self_unbind(owner.id)
    db = env["db"]
    db.expire_all()
    assert db.get(UserAccount, owner.id).student_id == b.id
    shell = db.get(UserAccount, db.get(WechatIdentity, wx_a.id).user_id)
    assert shell.id != owner.id and shell.student_id is None and shell.username is None
    assert IdentityService(db)._repo.list_role_codes(shell.id) == []
    assert set(IdentityService(db)._repo.list_role_codes(owner.id)) == {"STUDENT", "VOLUNTEER"}
    assert db.get(AuthSession, old_session.id).revoked_at is not None


def test_two_wechat_rebind_preserves_pending_and_submitted_records(env):
    a, b, owner, other, wx_a, wx_b, _ = seed(env)
    db = env["db"]
    original = owner.id
    IdentityService(db).student_self_unbind(original)
    db.expire_all()
    shell = db.get(WechatIdentity, wx_a.id).user_id
    code(db, a, "code-a")
    IdentityService(db).bind_student(shell, a.student_no, "code-a")
    code(db, b, "code-b")
    IdentityService(db).bind_student(other.id, b.student_no, "code-b")
    db.expire_all()
    assert db.get(WechatIdentity, wx_a.id).user_id != original
    assert db.get(WechatIdentity, wx_b.id).user_id == original
    assert db.get(UserAccount, original).student_id == b.id
    assert (
        len(
            db.scalars(
                select(InspectionAssignment).where(
                    InspectionAssignment.volunteer_user_id == original
                )
            ).all()
        )
        == 2
    )
    assert (
        len(
            db.scalars(
                select(InspectionSubmission).where(
                    InspectionSubmission.volunteer_user_id == original
                )
            ).all()
        )
        == 1
    )
    assert (
        db.scalar(
            select(InspectionAssignment.id).where(InspectionAssignment.volunteer_user_id == shell)
        )
        is None
    )


def test_admin_cannot_relabel_uid_with_inspection_history(env):
    a, _, owner, *_ = seed(env)
    with pytest.raises(ConflictError):
        IdentityService(env["db"]).student_binding_reset(
            actor_user_id=env["admin"].id,
            target_user_id=owner.id,
            new_student_no=a.student_no,
            reason=None,
            request_id=None,
        )


def test_redeem_refuses_disabled_existing_account(env):
    _, b, owner, other, wx_a, *_ = seed(env)
    db = env["db"]
    wx_a.user_id = env["accounts"]["wechat"].id
    owner.status = "INACTIVE"
    db.commit()
    code(db, b, "disabled-code")
    with pytest.raises((ConflictError, UnauthenticatedError)):
        IdentityService(db).bind_student(other.id, b.student_no, "disabled-code")


def test_claim_moves_only_live_wechat_sessions_and_refresh_keeps_student_uid(env):
    _, b, owner, other, wx_a, _, _ = seed(env)
    db = env["db"]
    wx_a.user_id = env["accounts"]["wechat"].id
    for kind, refresh, revoked in [
        ("WECHAT", "live", None),
        ("WEB", "web", None),
        ("WECHAT", "revoked", utcnow()),
    ]:
        db.add(
            AuthSession(
                user_id=other.id,
                client_type=kind,
                refresh_token_hash=hash_token(refresh),
                refresh_family_id=refresh,
                expires_at=utcnow() + timedelta(days=1),
                revoked_at=revoked,
            )
        )
    db.commit()
    code(db, b, "reclaim")
    service = IdentityService(db)
    service.bind_student(other.id, b.student_no, "reclaim")
    db.expire_all()
    sessions = {s.refresh_family_id: s for s in db.scalars(select(AuthSession)).all()}
    assert sessions["live"].user_id == owner.id and sessions["live"].is_valid
    assert sessions["web"].user_id == other.id and not sessions["web"].is_valid
    assert sessions["revoked"].user_id == other.id and not sessions["revoked"].is_valid
    with pytest.raises(UnauthenticatedError):
        service.resolve_session_user(other.id, sessions["live"].id)
    pair = service.refresh("live")
    from app.core.security import decode_access_token

    assert int(decode_access_token(pair.access_token)["sub"]) == owner.id


def test_stale_session_cannot_unbind_again_after_wechat_has_changed(env):
    _, _, owner, _, _, _, old_session = seed(env)
    service = IdentityService(env["db"])
    service.student_self_unbind(owner.id, session_id=old_session.id)
    with pytest.raises(UnauthenticatedError):
        service.student_self_unbind(owner.id, session_id=old_session.id)
    with pytest.raises(UnauthenticatedError):
        service.refresh("refresh-a")


@pytest.mark.parametrize("mode", ["privileged", "no-wechat", "multiple-wechat"])
def test_unbind_rejects_ambiguous_or_privileged_identity(env, mode):
    _, _, owner, _, wx_a, *_ = seed(env)
    db = env["db"]
    service = IdentityService(db)
    if mode == "privileged":
        role = service._repo.get_or_create_role("SUPER_ADMIN", "超管")
        service._repo.grant_role(owner.id, role.id)
    elif mode == "no-wechat":
        db.delete(wx_a)
    else:
        db.add(WechatIdentity(user_id=owner.id, appid="test", openid="second-wx"))
    db.commit()
    with pytest.raises(ConflictError):
        service.student_self_unbind(owner.id)


def test_unbind_audit_failure_rolls_back_new_account_and_identity(env, monkeypatch):
    _, b, owner, _, wx_a, *_ = seed(env)
    db = env["db"]
    original = owner.id
    service = IdentityService(db)

    def fail(**kwargs):
        raise RuntimeError("模拟审计失败")

    monkeypatch.setattr(service, "_record_audit", fail)
    with pytest.raises(RuntimeError):
        service.student_self_unbind(original)
    db.rollback()
    db.expire_all()
    assert db.get(WechatIdentity, wx_a.id).user_id == original
    assert db.get(UserAccount, original).student_id == b.id
    assert len(db.scalars(select(UserAccount)).all()) == 6


def test_orphaned_history_cannot_be_rebound_to_another_student(env):
    a, _, owner, *_ = seed(env)
    db = env["db"]
    owner.student_id = None
    db.commit()
    code(db, a, "orphan")
    with pytest.raises(ConflictError):
        IdentityService(db).bind_student(owner.id, a.student_no, "orphan")


def test_claim_cannot_take_over_management_account(env):
    _, b, owner, other, wx_a, *_ = seed(env)
    db = env["db"]
    wx_a.user_id = env["accounts"]["wechat"].id
    service = IdentityService(db)
    role = service._repo.get_or_create_role("TEACHER_ADMIN", "学院管理员")
    service._repo.grant_role(owner.id, role.id)
    db.commit()
    code(db, b, "privileged")
    with pytest.raises(ConflictError):
        service.bind_student(other.id, b.student_no, "privileged")


def test_http_rebind_relogin_refresh_returns_original_student_account(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.main import app
    from app.modules.identity.wechat import MockWechatCode2SessionClient

    a, b, owner, _, _, _, _ = seed(env)
    monkeypatch.setattr(get_settings(), "wechat_login_enabled", True)
    monkeypatch.setattr(get_settings(), "wechat_appid", "test")
    mock = MockWechatCode2SessionClient(code_to_openid={"wx-a": "wx-a", "wx-b": "wx-b"})
    monkeypatch.setattr("app.modules.identity.service.build_default_client", lambda: mock)
    app.dependency_overrides[get_db] = lambda: env["db"]
    code(env["db"], a, "api-code-a")
    code(env["db"], b, "api-code-b")

    def bearer(pair):
        return {"Authorization": f"Bearer {pair['access_token']}"}

    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/auth/wechat/login", json={"code": "wx-a"}).json()["data"]
            response = client.delete("/api/v1/me/student-binding", headers=bearer(first))
            assert response.status_code == 200, response.text
            assert client.get("/api/v1/me", headers=bearer(first)).status_code == 401
            fresh = client.post("/api/v1/auth/wechat/login", json={"code": "wx-a"}).json()["data"]
            assert fresh["need_binding"] is True
            assert (
                client.post(
                    "/api/v1/me/student-binding",
                    headers=bearer(fresh),
                    json={"student_no": a.student_no, "binding_code": "api-code-a"},
                ).status_code
                == 200
            )
            second = client.post("/api/v1/auth/wechat/login", json={"code": "wx-b"}).json()["data"]
            response = client.post(
                "/api/v1/me/student-binding",
                headers=bearer(second),
                json={"student_no": b.student_no, "binding_code": "api-code-b"},
            )
            assert response.status_code == 200, response.text
            assert client.get("/api/v1/me", headers=bearer(second)).status_code == 401
            refreshed = client.post(
                "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
            )
            assert refreshed.status_code == 200, refreshed.text
            me = client.get("/api/v1/me", headers=bearer(refreshed.json()["data"])).json()["data"]
            assert me["id"] == str(owner.id) and me["student_no"] == b.student_no
    finally:
        app.dependency_overrides.pop(get_db, None)
