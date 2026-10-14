"""管理员补权的数据库行为回归，SQLite 不证明 MySQL 并发锁。"""

from dataclasses import replace

import pytest
from app.core.database import Base
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.identity.account_schemas import (
    AdministratorAccountCreate,
    AdministratorAccountUpdate,
    PasswordReset,
)
from app.modules.identity.account_service import AccountService
from app.modules.identity.bootstrap_admin_management import grant_administrator_management
from app.modules.identity.models import Permission, Role, UserAccount
from app.modules.identity.policy import DEFAULT_ROLE_PERMISSIONS, can_manage_administrator
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser, IdentityService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def accounts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sync_registry(db)
        for uid, role in [(1, "SUPER_ADMIN"), (2, "SUPER_ADMIN"), (3, "TEACHER_ADMIN")]:
            db.add(
                UserAccount(
                    id=uid,
                    username=f"account{uid}",
                    display_name=f"Account {uid}",
                    status="ACTIVE",
                    roles=[db.scalar(select(Role).where(Role.code == role))],
                )
            )
        db.commit()
        yield db


def actor(uid):
    return CurrentUser(uid, f"account{uid}", f"Account {uid}", "ACTIVE", ["SUPER_ADMIN"], [])


@pytest.mark.parametrize(
    "roles,permissions,expected",
    [
        ({"SUPER_ADMIN"}, set(), False),
        ({"SUPER_ADMIN"}, {"administrator_account.manage"}, True),
        ({"TEACHER_ADMIN"}, {"administrator_account.manage"}, False),
        ({"STUDENT_AFFAIRS_MANAGER"}, {"administrator_account.manage"}, False),
    ],
)
def test_explicit_capability(roles, permissions, expected):
    assert can_manage_administrator(frozenset(roles), frozenset(permissions)) is expected


def test_registry_does_not_grant_capability_by_default(accounts):
    for permissions in DEFAULT_ROLE_PERMISSIONS.values():
        assert "administrator_account.manage" not in permissions
    assert "administrator_account.manage" not in IdentityRepository(
        accounts
    ).list_effective_permissions(1)
    sync_registry(accounts)
    assert "administrator_account.manage" not in IdentityRepository(
        accounts
    ).list_effective_permissions(2)


def test_bootstrap_only_designated_admin_and_is_idempotent(accounts):
    assert grant_administrator_management(accounts, 1) is True
    assert grant_administrator_management(accounts, 1) is False
    assert "administrator_account.manage" in IdentityRepository(
        accounts
    ).list_effective_permissions(1)
    assert "administrator_account.manage" not in IdentityRepository(
        accounts
    ).list_effective_permissions(2)
    with pytest.raises(PermissionDeniedError):
        grant_administrator_management(accounts, 3)


def test_misassigned_teacher_grant_does_not_become_effective(accounts):
    repo = IdentityRepository(accounts)
    perm = accounts.scalar(
        select(Permission).where(Permission.code == "administrator_account.manage")
    )
    repo.set_user_permission(3, perm.id, 1)
    accounts.commit()
    assert "administrator_account.manage" not in repo.list_effective_permissions(3)


def test_normal_admin_cannot_reset_another_admin(accounts):
    with pytest.raises(PermissionDeniedError):
        AccountService(accounts).reset_password(
            actor(2), 1, PasswordReset(new_password="TestPass_123", lock_version=0), None
        )
    assert accounts.get(UserAccount, 1).password_hash is None


def test_old_role_endpoint_cannot_elevate_or_change_admin(accounts):
    with pytest.raises(PermissionDeniedError):
        IdentityService(accounts).assign_roles(
            actor_user_id=2,
            target_user_id=3,
            desired_codes=["SUPER_ADMIN"],
            expected_version=0,
            reason=None,
            request_id=None,
        )


def test_platform_create_update_and_password_reset(accounts):
    grant_administrator_management(accounts, 1)
    accounts.commit()
    service = AccountService(accounts)
    new = service.create_administrator(
        actor(1),
        AdministratorAccountCreate(
            username="admin_new", display_name="New Admin", initial_password="TestPass_123"
        ),
        None,
    )
    assert new["roles"] == ["SUPER_ADMIN"]
    assert new["can_manage_administrators"] is False
    assert "password_hash" not in new
    changed = service.update_administrator(
        actor(1),
        int(new["id"]),
        AdministratorAccountUpdate(
            can_manage_administrators=True, lock_version=new["lock_version"]
        ),
        None,
    )
    assert changed["can_manage_administrators"] is True
    service.reset_password(
        actor(1),
        int(new["id"]),
        PasswordReset(new_password="AnotherPass_123", lock_version=changed["lock_version"]),
        None,
    )


def test_last_platform_manager_cannot_be_disabled_or_revoked(accounts):
    grant_administrator_management(accounts, 1)
    accounts.commit()
    for kwargs in [{"can_manage_administrators": False}, {"status": "DISABLED"}]:
        with pytest.raises(ConflictError):
            AccountService(accounts).update_administrator(
                actor(1),
                1,
                AdministratorAccountUpdate(
                    lock_version=accounts.get(UserAccount, 1).lock_version, **kwargs
                ),
                None,
            )
        accounts.rollback()


def test_revoked_permission_cannot_use_stale_actor(accounts):
    grant_administrator_management(accounts, 1)
    grant_administrator_management(accounts, 2)
    accounts.commit()
    service = AccountService(accounts)
    service.update_administrator(
        actor(2),
        1,
        AdministratorAccountUpdate(
            can_manage_administrators=False, lock_version=accounts.get(UserAccount, 1).lock_version
        ),
        None,
    )
    stale = replace(actor(1), permissions=["administrator_account.manage"])
    with pytest.raises(PermissionDeniedError):
        service.create_administrator(
            stale,
            AdministratorAccountCreate(
                username="not_created", display_name="No", initial_password="TestPass_123"
            ),
            None,
        )
