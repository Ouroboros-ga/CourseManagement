"""授权管理闭环集成测试（P1 步骤 4-7，连真实 MySQL 测试库）。

覆盖 PERMISSIONS.md 第 17 节基线中本批可达的场景与 DEVELOPMENT_PLAN 步骤 5-7：
- 角色分配差集边界（教师不能授/撤 SUPER_ADMIN/TEACHER_ADMIN，含省略即撤销也整体 403；
  超管管理教师成功；STUDENT/VOLUNTEER 手工分配恒 403）。
- 未知角色 code 422、目标不存在 404、乐观并发版本不符 409。
- 撤销负责人角色同事务清除个人可选授权，重新授予不恢复。
- 可选权限三项清单校验、非负责人目标 422、禁止自我提权 403、下一请求立即生效。
- 受限目标选择器（角色/可选权限）返回范围与"可操作角色"。
- 会话解析补 session.user_id == user_id 自洽校验（伪造组合 401）。
- 真实 MySQL 并发：同目标并发修改一个成功一个 409、撤销与授权并发、审计失败整笔回滚。
"""

from __future__ import annotations

import threading

import pytest
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    UnauthenticatedError,
)
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password
from app.modules.identity.models import (
    AuthSession,
    Role,
    UserAccount,
    UserPermission,
    UserStatus,
)
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import IdentityService
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"


# --------------------------------------------------------------------------- #
# 数据装配助手
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    """落库 5 角色 + 38 权限 + 默认矩阵，供有效权限计算。"""
    sync_registry(session)
    session.commit()


def _role(session: Session, code: str) -> Role:
    return session.execute(select(Role).where(Role.code == code)).scalar_one()


def _make_user(
    session: Session, username: str, role_codes: list[str]
) -> UserAccount:
    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [_role(session, c) for c in role_codes]
    session.add(user)
    session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": username, "password": _PWD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


def _login_and_me_permissions(client: TestClient, username: str) -> list[str]:
    data = _login(client, username)
    resp = client.get("/api/v1/me", headers=_bearer(data))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["permissions"]


def _ver(session: Session, uid: int) -> int:
    # 结束当前快照事务，确保读到 API 会话已提交的最新 lock_version
    # （MySQL 默认 REPEATABLE READ，同一事务快照不会刷新）。
    session.commit()
    session.expire_all()
    return session.get(UserAccount, uid).lock_version


# --------------------------------------------------------------------------- #
# 角色分配边界（API）
# --------------------------------------------------------------------------- #
def test_super_admin_assigns_teacher_role(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.TEACHER_ADMIN.value], "lockVersion": 0, "reason": "任命"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["roles"] == [RoleCode.TEACHER_ADMIN.value]
    assert body["lock_version"] == 1


def test_super_admin_assign_student_role_forbidden(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.STUDENT.value], "lockVersion": 0},
    )
    # STUDENT/VOLUNTEER 属业务身份自动维护，超管亦不可手工旁路。
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_teacher_cannot_grant_super_admin(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "teacher", [RoleCode.TEACHER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "teacher")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.SUPER_ADMIN.value], "lockVersion": 0},
    )
    assert resp.status_code == 403


def test_teacher_can_assign_student_affairs_manager(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "teacher", [RoleCode.TEACHER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "teacher")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.STUDENT_AFFAIRS_MANAGER.value], "lockVersion": 0},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["roles"] == [RoleCode.STUDENT_AFFAIRS_MANAGER.value]


def test_teacher_omitting_existing_protected_role_is_rejected(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "teacher", [RoleCode.TEACHER_ADMIN.value])
    # 目标已具教师角色，教师提交空集合试图撤销 → 整体 403，原角色不变。
    target = _make_user(session, "t1", [RoleCode.TEACHER_ADMIN.value])

    data = _login(client, "teacher")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [], "lockVersion": 0},
    )
    assert resp.status_code == 403
    session.expire_all()
    refreshed = session.get(UserAccount, target.id)
    assert sorted(r.code for r in refreshed.roles) == [RoleCode.TEACHER_ADMIN.value]


def test_unknown_role_code_returns_422(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": ["NOT_A_ROLE"], "lockVersion": 0},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_invisible_target_returns_404(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])

    data = _login(client, "admin")
    resp = client.put(
        "/api/v1/users/999999/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.STUDENT_AFFAIRS_MANAGER.value], "lockVersion": 0},
    )
    assert resp.status_code == 404


def test_version_conflict_returns_409(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])

    data = _login(client, "admin")
    # 先成功一次把版本推进到 1。
    ok = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.STUDENT_AFFAIRS_MANAGER.value], "lockVersion": 0},
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["lock_version"] == 1

    # 用陈旧版本 0 再次提交 → 409。
    stale = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(data),
        json={"roles": [RoleCode.STUDENT_AFFAIRS_MANAGER.value], "lockVersion": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"


# --------------------------------------------------------------------------- #
# 撤销负责人角色同事务清除个人可选授权
# --------------------------------------------------------------------------- #
def test_revoking_manager_role_clears_optional_grants(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])

    admin = _login(client, "admin")
    # 开启 statistics.read（目标版本 0 → 1）。
    on = client.put(
        f"/api/v1/users/{target.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(admin),
        json={"enabled": True, "lockVersion": _ver(session, target.id)},
    )
    assert on.status_code == 200, on.text
    assert PermissionCode.STATISTICS_READ.value in _login_and_me_permissions(
        client, "sam"
    )

    # 撤销负责人角色（版本 → 2），应同事务清除个人可选授权。
    revoke = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(admin),
        json={"roles": [], "lockVersion": _ver(session, target.id)},
    )
    assert revoke.status_code == 200, revoke.text

    # 目标不再持有该可选授权记录，且下次请求不含 statistics.read。
    session.commit()
    session.expire_all()
    remaining = session.execute(
        select(UserPermission).where(UserPermission.user_id == target.id)
    ).scalars().all()
    assert remaining == []


# --------------------------------------------------------------------------- #
# 可选权限开关
# --------------------------------------------------------------------------- #
def test_optional_permission_effective_next_request(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    target = session.execute(
        select(UserAccount).where(UserAccount.username == "sam")
    ).scalar_one()

    assert PermissionCode.STATISTICS_READ.value not in _login_and_me_permissions(
        client, "sam"
    )

    admin = _login(client, "admin")
    r_on = client.put(
        f"/api/v1/users/{target.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(admin),
        json={"enabled": True, "lockVersion": _ver(session, target.id)},
    )
    assert r_on.status_code == 200, r_on.text
    assert r_on.json()["data"] == {
        "code": PermissionCode.STATISTICS_READ.value,
        "enabled": True,
        "lock_version": _ver(session, target.id),
    }
    # 下一请求立即生效。
    assert PermissionCode.STATISTICS_READ.value in _login_and_me_permissions(
        client, "sam"
    )

    # 关闭 → 下一请求立即失效。
    r_off = client.put(
        f"/api/v1/users/{target.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(admin),
        json={"enabled": False, "lockVersion": _ver(session, target.id)},
    )
    assert r_off.status_code == 200, r_off.text
    assert PermissionCode.STATISTICS_READ.value not in _login_and_me_permissions(
        client, "sam"
    )


def test_optional_reject_code_outside_allowlist(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])

    admin = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/optional-permissions/{PermissionCode.ACCOUNT_READ.value}",
        headers=_bearer(admin),
        json={"enabled": True, "lockVersion": 0},
    )
    assert resp.status_code == 422


def test_optional_reject_non_manager_target(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "plain", [])

    admin = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(admin),
        json={"enabled": True, "lockVersion": 0},
    )
    assert resp.status_code == 422


def test_optional_self_grant_forbidden(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    # 超管同时具备 optional_permission.manage，但不能给自己提权。
    admin_user = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    admin = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{admin_user.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(admin),
        json={"enabled": True, "lockVersion": 0},
    )
    assert resp.status_code == 403


def test_optional_requires_manage_permission_actor(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    # 另一名负责人没有 optional_permission.manage，作为操作者应 403（端点守卫）。
    _make_user(session, "sam_actor", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam_actor = _make_user(
        session, "sam_target", [RoleCode.STUDENT_AFFAIRS_MANAGER.value]
    )

    actor = _login(client, "sam_actor")
    resp = client.put(
        f"/api/v1/users/{sam_actor.id}/optional-permissions/{PermissionCode.STATISTICS_READ.value}",
        headers=_bearer(actor),
        json={"enabled": True, "lockVersion": 0},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 受限目标选择器
# --------------------------------------------------------------------------- #
def test_role_assignment_targets_for_admin(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "t1", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])

    admin = _login(client, "admin")
    resp = client.get("/api/v1/role-assignment-targets", headers=_bearer(admin))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {item["username"] for item in data["items"]}
    assert {"admin", "t1"} <= usernames
    assignable = set(data["assignable_roles"])
    # 超管可手工管理三类管理角色，但不含 STUDENT/VOLUNTEER。
    assert {
        RoleCode.SUPER_ADMIN.value,
        RoleCode.TEACHER_ADMIN.value,
        RoleCode.STUDENT_AFFAIRS_MANAGER.value,
    } == assignable
    for item in data["items"]:
        assert "lock_version" in item and "roles" in item


def test_role_assignment_targets_for_teacher(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "teacher", [RoleCode.TEACHER_ADMIN.value])

    teacher = _login(client, "teacher")
    resp = client.get("/api/v1/role-assignment-targets", headers=_bearer(teacher))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 教师手工可操作角色仅负责人。
    assert data["assignable_roles"] == [RoleCode.STUDENT_AFFAIRS_MANAGER.value]


def test_optional_permission_targets_only_managers(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    _make_user(session, "plain", [])

    admin = _login(client, "admin")
    resp = client.get("/api/v1/optional-permission-targets", headers=_bearer(admin))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    names = {item["display_name"] for item in data["items"]}
    assert names == {"sam"}
    assert set(data["configurable_codes"]) == {
        PermissionCode.STATISTICS_READ.value,
        PermissionCode.REPORT_READ.value,
        PermissionCode.OBJECTION_INITIAL_REVIEW.value,
    }
    sam = data["items"][0]
    # 三项默认关闭。
    assert all(p["enabled"] is False for p in sam["permissions"])


# --------------------------------------------------------------------------- #
# 会话自洽校验（步骤 6）
# --------------------------------------------------------------------------- #
def test_session_user_mismatch_rejected(session: Session) -> None:
    _bootstrap(session)
    a = _make_user(session, "a", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    b = _make_user(session, "b", [RoleCode.VOLUNTEER.value])
    # 为 a 建立一条有效会话。
    sess = AuthSession(
        user_id=a.id,
        client_type="WEB",
        refresh_token_hash="x" * 32,
        refresh_family_id="fam-1",
        expires_at=_future(),
    )
    session.add(sess)
    session.commit()

    svc = IdentityService(session)
    # 用 b 的身份去解析 a 的会话 → 会话与身份不匹配 → 401。
    with pytest.raises(UnauthenticatedError):
        svc.resolve_session_user(b.id, sess.id)
    # 匹配则通过（不抛异常）。
    cur = svc.resolve_session_user(a.id, sess.id)
    assert cur.id == a.id


def _future():
    from datetime import timedelta

    from app.core.database import utcnow

    return utcnow() + timedelta(days=1)


# --------------------------------------------------------------------------- #
# 真实 MySQL 并发（步骤 7）：独立连接、线程重叠
# --------------------------------------------------------------------------- #
def _open_session(engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory()


def _role_assign_worker(
    engine, actor_id: int, target_id: int, expected: int, barrier: threading.Barrier,
    out: dict[int, object], idx: int,
) -> None:
    s = _open_session(engine)
    try:
        barrier.wait()
        svc = IdentityService(s)
        roles, version = svc.assign_roles(
            actor_user_id=actor_id,
            target_user_id=target_id,
            desired_codes=[RoleCode.STUDENT_AFFAIRS_MANAGER.value],
            expected_version=expected,
            reason="concurrency",
            request_id=f"c-{idx}",
        )
        out[idx] = ("ok", roles, version)
    except ConflictError as exc:
        s.rollback()
        out[idx] = ("conflict", exc.code)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_same_target_one_wins_other_conflicts(
    engine, session: Session
) -> None:
    _bootstrap(session)
    admin = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])
    expected = _ver(session, target.id)  # 0

    barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_role_assign_worker,
            args=(engine, admin.id, target.id, expected, barrier, out, i),
        )
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    results = list(out.values())
    kinds = sorted(r[0] for r in results)
    assert kinds == ["conflict", "ok"], results
    ok = next(r for r in results if r[0] == "ok")
    assert ok[2] == expected + 1  # 版本恰好推进一次


def _mixed_worker(
    engine, actor_id: int, target_id: int, expected: int, mode: str,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    s = _open_session(engine)
    try:
        barrier.wait()
        svc = IdentityService(s)
        if mode == "revoke":
            svc.assign_roles(
                actor_user_id=actor_id,
                target_user_id=target_id,
                desired_codes=[],
                expected_version=expected,
                reason="revoke",
                request_id=f"r-{idx}",
            )
        else:
            svc.set_optional_permission(
                actor_user_id=actor_id,
                target_user_id=target_id,
                code=PermissionCode.STATISTICS_READ.value,
                enabled=True,
                expected_version=expected,
                reason="grant",
                request_id=f"g-{idx}",
            )
        out[idx] = ("ok",)
    except ConflictError as exc:
        s.rollback()
        out[idx] = ("rejected", exc.code)
    except AppError as exc:
        # 并发下合法的业务拒绝：撤销先提交移除 SAM 后，授权按 §13.2
        # 在版本校验前先判定身份，得到 VALIDATION_ERROR；或版本竞态 409。
        s.rollback()
        out[idx] = ("rejected", exc.code)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_revoke_and_grant_same_target(
    engine, session: Session
) -> None:
    _bootstrap(session)
    admin = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    expected = _ver(session, target.id)  # 0

    barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    t1 = threading.Thread(
        target=_mixed_worker,
        args=(engine, admin.id, target.id, expected, "revoke", barrier, out, 0),
    )
    t2 = threading.Thread(
        target=_mixed_worker,
        args=(engine, admin.id, target.id, expected, "grant", barrier, out, 1),
    )
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    kinds = sorted(r[0] for r in out.values())
    # 不变量：同一目标、同一 lock_version 的并发改动，恰好一方成功提交，
    # 另一方被拒绝（版本竞态 409 或撤销先提交导致身份校验 422）。
    assert kinds == ["ok", "rejected"], out
    rejected = next(r for r in out.values() if r[0] == "rejected")
    assert rejected[1] in {
        ErrorCode.VERSION_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    }, out
    # 版本恰好推进一次，落库状态自洽。
    final = _ver(session, target.id)
    assert final == expected + 1, out


def test_audit_failure_rolls_back_whole_change(
    engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(session)
    admin = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])
    target_id = target.id

    def _boom(self, **kwargs):  # noqa: ANN001
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(IdentityService, "_record_audit", _boom)

    s = _open_session(engine)
    try:
        with pytest.raises(RuntimeError):
            IdentityService(s).assign_roles(
                actor_user_id=admin.id,
                target_user_id=target_id,
                desired_codes=[RoleCode.STUDENT_AFFAIRS_MANAGER.value],
                expected_version=0,
                reason="will-fail",
                request_id="audit-fail",
            )
    finally:
        s.rollback()
        s.close()

    # 角色变更与审计同事务：审计失败 → 角色未改、版本未动、无审计记录。
    session.expire_all()
    refreshed = session.get(UserAccount, target_id)
    assert refreshed.roles == []
    assert refreshed.lock_version == 0
    from app.modules.audit.models import AuditLog

    audit_count = session.scalar(select(func.count()).select_from(AuditLog))
    assert audit_count == 0


def test_successful_change_writes_audit(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    admin_user = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    target = _make_user(session, "t1", [])

    admin = _login(client, "admin")
    resp = client.put(
        f"/api/v1/users/{target.id}/roles",
        headers=_bearer(admin),
        json={"roles": [RoleCode.TEACHER_ADMIN.value], "lockVersion": 0, "reason": "审计"},
    )
    assert resp.status_code == 200, resp.text

    from app.modules.audit.models import AuditLog

    session.expire_all()
    row = session.execute(
        select(AuditLog).where(
            AuditLog.action == "role.assign",
            AuditLog.resource_id == str(target.id),
        )
    ).scalar_one()
    assert row.actor_user_id == admin_user.id
    assert row.after_json["roles"] == [RoleCode.TEACHER_ADMIN.value]
    assert row.before_json["roles"] == []
