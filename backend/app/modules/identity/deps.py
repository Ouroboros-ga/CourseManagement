"""身份与权限的 FastAPI 依赖。

- `get_current_user`：解析 Bearer 访问令牌并回查会话有效性（不能仅凭签名接受）。
- `require_roles(...)` / `require_permission(code)`：功能与角色守卫。
身份（学生 ID、操作者 ID）一律由服务端会话取得，不相信客户端传入（技术方案 6.3）。
具体资源归属判断留在各业务模块 permissions.py。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
from app.core.security import decode_access_token
from app.modules.identity.service import CurrentUser, IdentityService

_bearer = HTTPBearer(auto_error=False)


def _extract_bearer(
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[int, int]:
    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError()
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(str(payload["sub"]))
        session_id = int(str(payload["sid"]))
    except (KeyError, ValueError) as exc:
        raise UnauthenticatedError("访问令牌载荷无效") from exc
    return user_id, session_id


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> CurrentUser:
    user_id, session_id = _extract_bearer(credentials)
    return IdentityService(db).resolve_session_user(user_id, session_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def get_session_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
) -> int:
    """从访问令牌解析当前会话 ID（供登出等撤销操作使用）。"""
    _user_id, session_id = _extract_bearer(credentials)
    return session_id


SessionIdDep = Annotated[int, Depends(get_session_id)]


def require_roles(*role_codes: str) -> Callable[[CurrentUser], CurrentUser]:
    """要求当前用户拥有指定角色之一。"""

    def _dep(user: CurrentUserDep) -> CurrentUser:
        if not any(user.has_role(code) for code in role_codes):
            raise PermissionDeniedError()
        return user

    return _dep


def require_permission(code: str) -> Callable[[CurrentUser], CurrentUser]:
    """要求当前用户拥有指定（含可选）权限。"""

    def _dep(user: CurrentUserDep) -> CurrentUser:
        if not user.has_permission(code):
            raise PermissionDeniedError()
        return user

    return _dep


def require_binding_complete(
    user: CurrentUserDep,
) -> CurrentUser:
    """要求会话已完成学生绑定（非 PRE_BINDING 受限态）。

    未绑定微信用户仅可访问身份白名单接口（PERMISSIONS.md 1.6）。PRE_BINDING 用户
    默认无任何权限，功能守卫已能拦住多数接口；此依赖为"依赖本人 student_id"的业务
    接口再加一道纵深，防止其被意外赋予某权限后绕过绑定要求。
    """
    if user.pre_binding:
        raise PermissionDeniedError("请先完成学生身份绑定")
    return user


BindingCompleteDep = Annotated[CurrentUser, Depends(require_binding_complete)]
