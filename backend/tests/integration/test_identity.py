"""身份/权限模块集成测试（连真实 MySQL 测试库）。

覆盖：账号密码登录、令牌访问 /me、可选权限逐人开关、刷新轮换与重放检测、
Web 端 refresh 经 HttpOnly Cookie 传输与 CSRF 校验、原生客户端 JSON 体刷新、
登出撤销、登录失败锁定、学生绑定一次性核销。数据库不可用时整体跳过。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password, hash_token
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.models import (
    IdentityBindingToken,
    Permission,
    Role,
    UserAccount,
    UserPermission,
    UserStatus,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_COOKIE = "refresh_token"


def _seed_admin(session: Session, username: str = "admin") -> int:
    role = Role(code=RoleCode.SUPER_ADMIN.value, name="超级管理员")
    session.add(role)
    session.flush()
    admin = UserAccount(
        username=username,
        password_hash=hash_password("Admin#123"),
        display_name="系统管理员",
        status=UserStatus.ACTIVE.value,
    )
    admin.roles = [role]
    session.add(admin)
    session.commit()
    return admin.id


def _login(client: TestClient, username: str = "admin", password: str = "Admin#123") -> dict:
    """Web 登录：响应体只含访问令牌，刷新凭证进 Cookie（httpx 自动存 jar 并回传）。"""
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_web_login_sets_cookie_and_omits_refresh_in_body(
    client: TestClient, session: Session
) -> None:
    _seed_admin(session)
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": "admin", "password": "Admin#123"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 契约：Web 响应体绝不出现 refresh_token，改由 HttpOnly Cookie 下发。
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 15 * 60
    assert "refresh_token" not in data

    # Cookie 已下发且带 HttpOnly / SameSite=Lax / 限定 Path。
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert f"{_COOKIE}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    # 测试环境 COOKIE_SECURE=false（见 conftest），故不应带 secure。
    assert "secure" not in set_cookie


def test_login_wrong_password_401(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    resp = client.post(
        "/api/v1/auth/web/login",
        json={"username": "admin", "password": "nope-nope"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_me_returns_identity_with_role(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    tokens = _login(client)
    resp = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["username"] == "admin"
    assert RoleCode.SUPER_ADMIN.value in data["roles"]
    assert resp.headers.get("X-Request-Id")


def test_unauthenticated_me_returns_401(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401


def test_optional_permission_granted_then_revoked(
    client: TestClient, session: Session
) -> None:
    perm = Permission(code=PermissionCode.STATISTICS_READ.value, name="统计查看")
    session.add(perm)
    session.flush()

    user = UserAccount(
        username="staff1",
        password_hash=hash_password("Staff#123"),
        display_name="职工",
        status=UserStatus.ACTIVE.value,
    )
    session.add(user)
    session.commit()
    uid = user.id

    def perms_via_api() -> list[str]:
        tokens = _login(client, "staff1", "Staff#123")
        resp = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        return resp.json()["data"]["permissions"]

    # 默认关闭
    assert PermissionCode.STATISTICS_READ.value not in perms_via_api()

    # 逐人开启
    session.expire_all()
    user = session.get(UserAccount, uid)
    user.permissions_grant = None  # 占位属性，忽略
    session.add(
        UserPermission(user_id=uid, permission_id=perm.id, granted_by=uid)
    )
    session.commit()
    assert PermissionCode.STATISTICS_READ.value in perms_via_api()

    # 关闭后下一次请求立即生效（不使用长期权限缓存，技术方案 6.3）
    row = session.query(UserPermission).filter_by(user_id=uid).one()
    session.delete(row)
    session.commit()
    assert PermissionCode.STATISTICS_READ.value not in perms_via_api()


def test_refresh_rotation_and_replay_detection(
    client: TestClient, session: Session
) -> None:
    _seed_admin(session)
    _login(client)  # Cookie 进入 httpx jar
    r1 = client.cookies.get(_COOKIE)
    assert r1

    # 正常轮换：浏览器自动带 Cookie，新凭证写回 Cookie，响应体不含 refresh。
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200, resp.text
    assert "refresh_token" not in resp.json()["data"]
    r2 = client.cookies.get(_COOKIE)
    assert r2 and r2 != r1

    # 重放旧凭证 → 撤销整个刷新族，返回 401
    client.cookies.clear()
    client.cookies.set(_COOKIE, r1)
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    # 连刚换出的新凭证也应随族失效
    client.cookies.clear()
    client.cookies.set(_COOKIE, r2)
    after_replay = client.post("/api/v1/auth/refresh")
    assert after_replay.status_code == 401


def test_refresh_cookie_path_rejects_cross_site_request(
    client: TestClient, session: Session
) -> None:
    _seed_admin(session)
    _login(client)

    # 携带白名单外的 Origin → CSRF 拒绝（且不改动作废 Cookie）
    bad_origin = client.post(
        "/api/v1/auth/refresh", headers={"Origin": "https://evil.example"}
    )
    assert bad_origin.status_code == 403
    assert bad_origin.json()["code"] == "CSRF_FAILED"

    # Sec-Fetch-Site 显式 cross-site → CSRF 拒绝
    cross = client.post(
        "/api/v1/auth/refresh", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert cross.status_code == 403
    assert cross.json()["code"] == "CSRF_FAILED"

    # 白名单内 Origin 应通过（证明拒绝逻辑精确，非一刀切）
    ok = client.post("/api/v1/auth/refresh", headers={"Origin": "http://app.test"})
    assert ok.status_code == 200, ok.text


def test_refresh_native_client_uses_json_body(
    client: TestClient, session: Session
) -> None:
    _seed_admin(session)
    _login(client)
    token = client.cookies.get(_COOKIE)
    assert token

    # 模拟无 Cookie 语义的原生/小程序客户端：清空 jar，改从 JSON 体携带 refresh
    client.cookies.clear()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 原生路径随体返回新 refresh；且不下发 Set-Cookie。
    assert data["access_token"] and data["refresh_token"]
    assert data["refresh_token"] != token
    assert "set-cookie" not in {k.lower() for k in resp.headers}


def test_refresh_without_credential_is_401(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    # 既无 Cookie 也无 body → 缺少刷新凭证
    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_logout_revokes_access_and_clears_cookie(
    client: TestClient, session: Session
) -> None:
    _seed_admin(session)
    tokens = _login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.get("/api/v1/me", headers=headers).status_code == 200
    resp = client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 204
    # 登出显式清除 refresh Cookie（置空值 + 过期）
    cleared = resp.headers.get("set-cookie", "").lower()
    assert f"{_COOKIE}=" in cleared and ("max-age=0" in cleared or "expires" in cleared)
    # 登出后访问令牌对应会话已撤销
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_login_lockout_after_max_failures(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/web/login",
            json={"username": "admin", "password": "bad-password"},
        )
        assert resp.status_code == 401
    # 第 6 次触发锁定
    resp = client.post(
        "/api/v1/auth/web/login",
        json={"username": "admin", "password": "Admin#123"},
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "STATE_CONFLICT"


def test_student_binding_one_time(client: TestClient, session: Session) -> None:
    _seed_admin(session)
    ac = AdministrativeClass(class_code="C1", class_name="班级一", grade_year=2024)
    session.add(ac)
    session.flush()
    stu = Student(
        student_no="S001", name="张三", administrative_class_id=ac.id
    )
    session.add(stu)
    session.commit()

    code = uuid.uuid4().hex + uuid.uuid4().hex  # 32+ 字符模拟绑定码明文
    session.add(
        IdentityBindingToken(
            student_id=stu.id,
            token_hash=hash_token(code),
            status="UNUSED",
            expires_at=utcnow() + timedelta(hours=1),
        )
    )
    session.commit()

    tokens = _login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = client.post(
        "/api/v1/me/student-binding",
        headers=headers,
        json={"student_no": "S001", "binding_code": code},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["data"]
    assert result["student_no"] == "S001"

    # 绑定码已用，不能再次核销
    resp2 = client.post(
        "/api/v1/me/student-binding",
        headers=headers,
        json={"student_no": "S001", "binding_code": code},
    )
    assert resp2.status_code == 409
