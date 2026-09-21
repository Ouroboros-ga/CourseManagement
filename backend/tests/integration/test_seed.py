"""种子同步验证（开发路线 P1 第 2 步）——连真实 MySQL。

断言种子把注册表精确对齐矩阵且幂等，并且：
- role_permission 精确等于 DEFAULT_ROLE_PERMISSIONS 展开（不依赖数量，逐项比对）；
- 二次执行不重复写（report.changed 为 False，计数不变）；
- 不动 user_permission 个人授权；
- 超管账号仅首次创建，二次执行不重置口令、不重复建号。
"""

from __future__ import annotations

import pytest
from app.core.permissions import PermissionCode
from app.modules.identity.models import (
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserPermission,
    UserStatus,
)
from app.modules.identity.policy import DEFAULT_ROLE_PERMISSIONS
from app.modules.identity.seed import ensure_admin_account, sync_registry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _expected_links() -> set[tuple[str, str]]:
    return {
        (role_code, perm_code)
        for role_code, perms in DEFAULT_ROLE_PERMISSIONS.items()
        for perm_code in perms
    }


def _db_links(session: Session) -> set[tuple[str, str]]:
    rows = session.execute(
        select(Role.code, Permission.code)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
    ).all()
    return {(r[0], r[1]) for r in rows}


def _perm_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Permission)).scalar_one()


def _link_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(RolePermission)).scalar_one()


def test_sync_registry_matches_matrix_and_is_idempotent(session: Session) -> None:
    report = sync_registry(session)
    session.commit()

    assert _perm_count(session) == len(PermissionCode)
    assert _db_links(session) == _expected_links()
    assert _link_count(session) == sum(len(v) for v in DEFAULT_ROLE_PERMISSIONS.values())
    # 首次应有大量新增关联（初始库角色权限为空）。
    assert report.changed is True

    # 二次执行：无变化、不重复写。
    second = sync_registry(session)
    session.commit()
    assert second.changed is False
    assert second.created_permissions == []
    assert second.created_roles == []
    assert second.added_links == []
    assert second.removed_links == []
    assert _perm_count(session) == len(PermissionCode)
    assert _link_count(session) == sum(len(v) for v in DEFAULT_ROLE_PERMISSIONS.values())


def test_sync_registry_preserves_personal_grants(session: Session) -> None:
    sync_registry(session)
    session.commit()

    # 造一个用户与一条个人可选授权（user_permission）。
    sam_role = session.execute(
        select(Role).where(Role.code == "STUDENT_AFFAIRS_MANAGER")
    ).scalar_one()
    stat_perm = session.execute(
        select(Permission).where(Permission.code == "statistics.read")
    ).scalar_one()
    user = UserAccount(
        username="sam_probe", display_name="负责人探测", status=UserStatus.ACTIVE.value
    )
    user.roles = [sam_role]
    session.add(user)
    session.flush()
    granter = UserAccount(username="grantor", display_name="授予者", status=UserStatus.ACTIVE.value)
    session.add(granter)
    session.flush()
    session.add(
        UserPermission(user_id=user.id, permission_id=stat_perm.id, granted_by=granter.id)
    )
    session.commit()

    before = session.execute(
        select(func.count()).select_from(UserPermission)
    ).scalar_one()
    assert before == 1

    # 再次同步注册表不得清理个人授权。
    sync_registry(session)
    session.commit()
    after = session.execute(
        select(func.count()).select_from(UserPermission)
    ).scalar_one()
    assert after == 1
    assert _db_links(session) == _expected_links()


def test_ensure_admin_account_no_reset_no_duplicate(session: Session) -> None:
    sync_registry(session)
    session.commit()

    created = ensure_admin_account(
        session, username="admin", password="First#Pass1", display_name="超管"
    )
    session.commit()
    assert created is True

    first_hash = session.execute(
        select(UserAccount.password_hash).where(UserAccount.username == "admin")
    ).scalar_one()

    # 二次执行：不建号、不重置口令。
    created_again = ensure_admin_account(
        session, username="admin", password="Second#Pass2", display_name="超管"
    )
    session.commit()
    assert created_again is False

    rows = session.execute(
        select(func.count()).select_from(UserAccount).where(UserAccount.username == "admin")
    ).scalar_one()
    assert rows == 1
    kept_hash = session.execute(
        select(UserAccount.password_hash).where(UserAccount.username == "admin")
    ).scalar_one()
    assert kept_hash == first_hash
