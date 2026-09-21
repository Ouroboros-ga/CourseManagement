"""微信身份闭环集成测试（P2，连真实 MySQL 测试库）。

覆盖 PERMISSIONS.md 1.4/1.6、9.2 与 DEVELOPMENT_PLAN P2：
- code2session 客户端错误映射：功能未开 403、凭证无效 401、上游/超时 502。
- 首次微信登录自动建"无口令"账号 + 返回 need_binding=True + 受限会话（PRE_BINDING）。
- PRE_BINDING 用户可读 /me（binding_required=true），但被功能权限守卫拦住（403）。
- 管理员签发一次性绑定码 → 用户核销 → 自动授予 STUDENT、权限即时生效、二次核销 409。
- 真实 MySQL 并发：同一码两账号并发核销恰好一成功一被拒（FOR UPDATE 串行点）。
- 绑定码作废：UNUSED→OK、USED→409、已作废幂等；签发只返回明文一次、库中只存摘要。
- 换绑/解绑联动自动身份并撤销旧会话；Web 管理员因持有角色不受 PRE_BINDING 限制。
- 敏感字段（session_key/appid/secret）绝不出现在任何响应体。
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.permissions import RoleCode
from app.core.security import hash_password, hash_token
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.models import (
    IdentityBindingToken,
    UserAccount,
    UserStatus,
    WechatIdentity,
)
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import IdentityService
from app.modules.identity.wechat import MockWechatCode2SessionClient
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_WECHAT_ENDPOINT = "/api/v1/auth/wechat/login"
_APPID = "wx_test_appid"


# --------------------------------------------------------------------------- #
# 数据装配 / 上下文助手
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    sync_registry(session)
    session.commit()


def _make_admin(session: Session) -> int:
    from app.modules.identity.models import Role

    role = session.execute(
        select(Role).where(Role.code == RoleCode.SUPER_ADMIN.value)
    ).scalar_one()
    admin = UserAccount(
        username="admin",
        password_hash=hash_password(_PWD),
        display_name="系统管理员",
        status=UserStatus.ACTIVE.value,
    )
    admin.roles = [role]
    session.add(admin)
    session.commit()
    return admin.id


def _make_user(session: Session, username: str, role_codes: list[str]) -> UserAccount:
    from app.modules.identity.models import Role

    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [
        session.execute(select(Role).where(Role.code == c)).scalar_one()
        for c in role_codes
    ]
    session.add(user)
    session.commit()
    return user


def _make_student(session: Session, student_no: str) -> Student:
    ac = session.scalar(
        select(AdministrativeClass).where(AdministrativeClass.class_code == "C1")
    )
    if ac is None:
        ac = AdministrativeClass(
            class_code="C1", class_name="班级一", grade_year=2024
        )
        session.add(ac)
        session.flush()
    stu = Student(student_no=student_no, name=student_no, administrative_class_id=ac.id)
    session.add(stu)
    session.commit()
    return stu


def _web_login(client: TestClient, username: str = "admin") -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": username, "password": _PWD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


def _enable_wechat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mock: MockWechatCode2SessionClient,
) -> None:
    """开启微信登录并把 code2session 换成测试替身。"""
    monkeypatch.setenv("WECHAT_LOGIN_ENABLED", "true")
    monkeypatch.setenv("WECHAT_APPID", _APPID)
    import app.core.config as cfg
    import app.modules.identity.service as svc

    monkeypatch.setattr(svc, "build_default_client", lambda: mock)
    cfg.get_settings.cache_clear()


def _wechat_login(client: TestClient, code: str) -> object:
    return client.post(_WECHAT_ENDPOINT, json={"code": code})


def _wechat_user_id(session: Session, openid: str) -> int:
    session.commit()
    session.expire_all()
    return session.execute(
        select(WechatIdentity.user_id).where(WechatIdentity.openid == openid)
    ).scalar_one()


# --------------------------------------------------------------------------- #
# code2session 错误映射与登录开关
# --------------------------------------------------------------------------- #
def test_wechat_login_disabled_returns_403(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    monkeypatch.setenv("WECHAT_LOGIN_ENABLED", "false")
    import app.core.config as cfg

    cfg.get_settings.cache_clear()
    resp = _wechat_login(client, "anycode")
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_wechat_login_invalid_code_returns_401(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(invalid_codes={"badcode"}),
    )
    resp = _wechat_login(client, "badcode")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_wechat_login_timeout_returns_502(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(timeout_codes={"slowcode"}),
    )
    resp = _wechat_login(client, "slowcode")
    assert resp.status_code == 502
    assert resp.json()["code"] == "UPSTREAM_UNAVAILABLE"


def test_wechat_login_upstream_error_returns_502(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(upstream_error_codes={"busycode"}),
    )
    resp = _wechat_login(client, "busycode")
    assert resp.status_code == 502
    assert resp.json()["code"] == "UPSTREAM_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# 首次登录建号 + PRE_BINDING 受限会话
# --------------------------------------------------------------------------- #
def test_first_wechat_login_creates_account_and_pre_binding(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(code_to_openid={"c1": "openid_A"}),
    )
    resp = _wechat_login(client, "c1")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 小程序无 Cookie 语义：refresh 随体返回；need_binding 引导绑定页。
    assert data["access_token"] and data["refresh_token"]
    assert data["need_binding"] is True
    assert data["expires_in"] == 15 * 60
    # 敏感字段绝不外泄。
    body = resp.text
    for secret in ("session_key", "mock_session_key", _APPID, "secret"):
        assert secret not in body

    # /me 处于受限态。
    me = client.get("/api/v1/me", headers=_bearer(data))
    assert me.status_code == 200, me.text
    m = me.json()["data"]
    assert m["binding_required"] is True
    assert m["roles"] == []
    assert m["permissions"] == []
    assert m["username"] is None

    # 建号落库校验：无口令、无角色，仅有微信身份关联。
    uid = _wechat_user_id(session, "openid_A")
    session.expire_all()
    created = session.get(UserAccount, uid)
    assert created.password_hash is None
    assert created.username is None
    assert created.student_id is None


def test_pre_binding_user_blocked_from_permission_guarded_endpoint(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(code_to_openid={"c1": "openid_A"}),
    )
    data = _wechat_login(client, "c1").json()["data"]
    resp = client.get("/api/v1/role-assignment-targets", headers=_bearer(data))
    # 无任何有效权限 → 功能守卫 403。
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


# --------------------------------------------------------------------------- #
# 完整链路：签发码 → 核销 → 自动授 STUDENT → 一次性
# --------------------------------------------------------------------------- #
def _issue_code(client: TestClient, admin: dict, student_id: int) -> tuple[str, str]:
    r = client.post(
        f"/api/v1/students/{student_id}/binding-tokens",
        headers=_bearer(admin),
        json={"reason": "现场发放"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    return body["token_id"], body["plaintext_code"]


def test_full_flow_issue_bind_autogrant_and_one_time(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    stu = _make_student(session, "S001")
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(code_to_openid={"wx": "openid_A"}),
    )

    admin = _web_login(client)
    token_id, code = _issue_code(client, admin, stu.id)

    data = _wechat_login(client, "wx").json()["data"]
    # 绑定前受限。
    assert client.get("/api/v1/me", headers=_bearer(data)).json()["data"][
        "binding_required"
    ] is True

    # 核销绑定 → STUDENT 自动授予。
    bind = client.post(
        "/api/v1/me/student-binding",
        headers=_bearer(data),
        json={"student_no": "S001", "binding_code": code},
    )
    assert bind.status_code == 200, bind.text
    assert bind.json()["data"]["student_no"] == "S001"

    me = client.get("/api/v1/me", headers=_bearer(data))
    m = me.json()["data"]
    assert m["binding_required"] is False
    assert RoleCode.STUDENT.value in m["roles"]
    assert m["permissions"]  # STUDENT 有效权限即时生效

    # 同一码二次核销 → 409。
    reuse = client.post(
        "/api/v1/me/student-binding",
        headers=_bearer(data),
        json={"student_no": "S001", "binding_code": code},
    )
    assert reuse.status_code == 409

    # 换绑到另一账号：即便持有某功能权限，PRE_BINDING 纵深守卫也应拦截——
    # 这里以"已绑定账号不能再次自助绑定"体现管理端流程约束。
    second = client.post(
        "/api/v1/me/student-binding",
        headers=_bearer(data),
        json={"student_no": "S001", "binding_code": "x" * 16},
    )
    assert second.status_code == 409  # 该账号已绑定


# --------------------------------------------------------------------------- #
# 真实 MySQL 并发：一次性码不可双花
# --------------------------------------------------------------------------- #
def _open_session(engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory()


def _bind_worker(
    engine, user_id: int, student_no: str, code: str, barrier: threading.Barrier,
    out: dict[int, object], idx: int,
) -> None:
    s = _open_session(engine)
    try:
        barrier.wait()
        IdentityService(s).bind_student(user_id, student_no, code)
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("rejected", type(exc).__name__)
    finally:
        s.close()


def test_concurrent_redeem_same_code_only_one_wins(
    engine, session: Session
) -> None:
    _bootstrap(session)
    # 两个不同账号、同一个学生的一次性码并发核销。
    u1 = _make_user(session, "u1", [])
    u2 = _make_user(session, "u2", [])
    stu = _make_student(session, "S001")
    code = "CONCURRENT-CODE-12345"
    session.add(
        IdentityBindingToken(
            student_id=stu.id,
            token_hash=hash_token(code),
            status="UNUSED",
            expires_at=utcnow() + timedelta(hours=1),
        )
    )
    session.commit()

    barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    t1 = threading.Thread(
        target=_bind_worker, args=(engine, u1.id, "S001", code, barrier, out, 0)
    )
    t2 = threading.Thread(
        target=_bind_worker, args=(engine, u2.id, "S001", code, barrier, out, 1)
    )
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    kinds = sorted(r[0] for r in out.values())
    assert kinds == ["ok", "rejected"], out

    # 落库不变量：该学生只绑定到一个账号；该码已 USED。
    session.commit()
    session.expire_all()
    bound = session.scalars(
        select(UserAccount).where(UserAccount.student_id == stu.id)
    ).all()
    assert len(bound) == 1
    token = session.execute(
        select(IdentityBindingToken).where(
            IdentityBindingToken.token_hash == hash_token(code)
        )
    ).scalar_one()
    assert token.status == "USED"
    assert token.used_at is not None


# --------------------------------------------------------------------------- #
# 绑定码作废与幂等
# --------------------------------------------------------------------------- #
def test_revoke_unused_binding_token_ok(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_admin(session)
    stu = _make_student(session, "S001")
    admin = _web_login(client)
    token_id, _ = _issue_code(client, admin, stu.id)

    r = client.post(
        f"/api/v1/binding-tokens/{token_id}/revoke",
        headers=_bearer(admin),
        json={"reason": "发错学生"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["token_id"] == token_id
    # 再作废 → 幂等成功。
    r2 = client.post(
        f"/api/v1/binding-tokens/{token_id}/revoke",
        headers=_bearer(admin),
        json={"reason": "重复作废"},
    )
    assert r2.status_code == 200, r2.text


def test_revoke_used_binding_token_409(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    _make_admin(session)
    stu = _make_student(session, "S001")
    _enable_wechat(
        client,
        monkeypatch,
        MockWechatCode2SessionClient(code_to_openid={"wx": "openid_A"}),
    )
    admin = _web_login(client)
    token_id, code = _issue_code(client, admin, stu.id)
    data = _wechat_login(client, "wx").json()["data"]
    bind = client.post(
        "/api/v1/me/student-binding",
        headers=_bearer(data),
        json={"student_no": "S001", "binding_code": code},
    )
    assert bind.status_code == 200, bind.text

    r = client.post(
        f"/api/v1/binding-tokens/{token_id}/revoke",
        headers=_bearer(admin),
        json={"reason": "已核销还想作废"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "STATE_CONFLICT"


def test_binding_token_plaintext_once_and_only_hash_stored(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_admin(session)
    stu = _make_student(session, "S001")
    admin = _web_login(client)
    r = client.post(
        f"/api/v1/students/{stu.id}/binding-tokens",
        headers=_bearer(admin),
        json={"reason": "只回显一次"},
    )
    assert r.status_code == 200, r.text
    plaintext = r.json()["data"]["plaintext_code"]
    assert plaintext

    # 库中仅存摘要，明文不落库。
    session.commit()
    session.expire_all()
    tok = session.scalar(
        select(IdentityBindingToken).where(
            IdentityBindingToken.student_id == stu.id
        )
    )
    assert tok is not None
    assert tok.token_hash != plaintext
    assert tok.token_hash == hash_token(plaintext)
    assert plaintext not in tok.token_hash


# --------------------------------------------------------------------------- #
# 换绑 / 解绑：自动身份联动 + 撤销旧会话
# --------------------------------------------------------------------------- #
def test_admin_rebind_switches_student_and_revokes_sessions(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_admin(session)
    s1 = _make_student(session, "S001")
    _make_student(session, "S002")
    from app.modules.identity.models import Role

    student_role = session.execute(
        select(Role).where(Role.code == RoleCode.STUDENT.value)
    ).scalar_one()
    target = _make_user(session, "stu_user", [])
    # 先绑定到 S001 并持有 STUDENT。
    target.student_id = s1.id
    target.roles = [student_role]
    session.commit()
    uid = target.id

    # 该用户旧 Web 会话，换绑后应失效。
    old = _web_login(client, "stu_user")
    assert client.get("/api/v1/me", headers=_bearer(old)).status_code == 200

    admin = _web_login(client)
    r = client.post(
        f"/api/v1/users/{uid}/student-binding-reset",
        headers=_bearer(admin),
        json={"new_student_no": "S002", "reason": "学号纠正"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["revoked_sessions"] >= 1
    assert body["student_id"] is not None

    # 旧访问令牌随会话撤销立即失效。
    assert client.get("/api/v1/me", headers=_bearer(old)).status_code == 401

    # 重新登录仍是 STUDENT（换绑保持自动身份）。
    new = _web_login(client, "stu_user")
    me = client.get("/api/v1/me", headers=_bearer(new)).json()["data"]
    assert RoleCode.STUDENT.value in me["roles"]
    assert me["binding_required"] is False


def test_admin_unbind_removes_student_and_revokes_sessions(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_admin(session)
    s1 = _make_student(session, "S001")
    from app.modules.identity.models import Role

    target = _make_user(session, "stu_user", [])
    student_role = session.execute(
        select(Role).where(Role.code == RoleCode.STUDENT.value)
    ).scalar_one()
    target.student_id = s1.id
    target.roles = [student_role]
    session.commit()
    uid = target.id

    old = _web_login(client, "stu_user")
    admin = _web_login(client)
    r = client.post(
        f"/api/v1/users/{uid}/student-binding-reset",
        headers=_bearer(admin),
        json={"new_student_no": None, "reason": "退学解绑"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["student_id"] is None
    assert r.json()["data"]["revoked_sessions"] >= 1

    # 解绑后账号无任何角色（回到需要重新绑定的开放态），旧会话失效。
    assert client.get("/api/v1/me", headers=_bearer(old)).status_code == 401
    new = _web_login(client, "stu_user")
    me = client.get("/api/v1/me", headers=_bearer(new)).json()["data"]
    assert me["roles"] == []


# --------------------------------------------------------------------------- #
# Web 管理员不受 PRE_BINDING 限制
# --------------------------------------------------------------------------- #
def test_web_admin_with_roles_not_pre_binding(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    _make_admin(session)
    admin = _web_login(client)
    me = client.get("/api/v1/me", headers=_bearer(admin))
    assert me.status_code == 200, me.text
    data = me.json()["data"]
    # 管理员无 student_id，但持有 SUPER_ADMIN 角色 → 不进入受限态。
    assert data["binding_required"] is False
    assert RoleCode.SUPER_ADMIN.value in data["roles"]
