"""指定已有管理员的平台补权初始化；不创建角色、不修改口令。"""

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import session_scope
from app.core.exceptions import ConflictError, ErrorCode, PermissionDeniedError
from app.modules.audit.models import AuditLog
from app.modules.identity.account_service import lock_admin_registry
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository


def grant_administrator_management(session: Session, user_id: int) -> bool:
    lock_admin_registry(session)
    repo = IdentityRepository(session)
    user = repo.get_user_by_id_for_update(user_id)
    if user is None or not user.is_active or "SUPER_ADMIN" not in repo.list_role_codes(user_id):
        raise PermissionDeniedError("仅能为有效的既有管理员初始化平台能力")
    permission = repo.get_permission_by_code("administrator_account.manage")
    if permission is None:
        raise ConflictError(ErrorCode.STATE_CONFLICT, "请先迁移并同步权限注册表")
    if "administrator_account.manage" in repo.list_effective_permissions(user_id):
        return False
    repo.set_user_permission(user_id, permission.id, user_id)
    user.lock_version += 1
    session.add(
        AuditLog(
            actor_user_id=user_id,
            action="account.administrator.bootstrap",
            resource_type="user_account",
            resource_id=str(user_id),
            before_json={"can_manage_administrators": False},
            after_json={"can_manage_administrators": True},
        )
    )
    session.flush()
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    with session_scope() as session:
        user = session.scalar(select(UserAccount).where(UserAccount.username == args.username))
        if user is None:
            raise SystemExit("指定管理员不存在")
        changed = grant_administrator_management(session, user.id)
        print(
            json.dumps(
                {"username": user.username, "changed": changed, "can_manage_administrators": True}
            )
        )


if __name__ == "__main__":
    main()
