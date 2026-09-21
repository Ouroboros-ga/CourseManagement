"""身份与权限路由：处理 HTTP，业务与事务交给 Service。

Router 只做参数解析、依赖装配与响应封装，不写业务流程（技术方案第 5 节）。

令牌传输契约（技术方案 7.1）：
- Web：access 走内存 + Authorization 头；refresh 经 HttpOnly Cookie 下发，前端 JS 读不到；
  /auth/refresh 从 Cookie 取值并做 CSRF 校验；/auth/logout 清除该 Cookie。
- 小程序等原生客户端无 Cookie 语义：refresh 继续在 JSON 请求/响应体中传递。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import CsrfError, UnauthenticatedError
from app.core.permissions import PermissionCode
from app.modules.identity.deps import CurrentUserDep, SessionIdDep, require_permission
from app.modules.identity.schemas import (
    BindingTokenIssueRequest,
    BindingTokenIssueResult,
    BindingTokenRevokeRequest,
    CurrentUserResponse,
    OptionalPermissionResult,
    OptionalPermissionTargetsResponse,
    OptionalPermissionUpdate,
    RefreshRequest,
    RoleAssignmentRequest,
    RoleAssignmentResult,
    RoleAssignmentTargetsResponse,
    StudentBindingRequest,
    StudentBindingResetRequest,
    StudentBindingResetResult,
    StudentBindingResult,
    WebLoginRequest,
    WechatLoginRequest,
    WechatLoginResult,
)
from app.modules.identity.service import CurrentUser, IdentityService

router = APIRouter(tags=["auth"])

# refresh Cookie 作用路径：仅覆盖 auth 子路径，缩小暴露面。
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def get_service(db: Annotated[Session, Depends(get_db)]) -> IdentityService:
    return IdentityService(db)


ServiceDep = Annotated[IdentityService, Depends(get_service)]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_cookie_max_age,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
    )


def _assert_csrf_ok(request: Request) -> None:
    """对 Cookie 承载的写接口做 CSRF 纵深校验。

    主防线是 SameSite=Lax（跨站 POST 不附带 Cookie）；此处叠加：
    - Sec-Fetch-Site 显式为 cross-site → 直接拒绝（浏览器托管，不可伪造）。
    - 携带 Origin → 必须命中白名单。
    - 无 Origin 且非 cross-site（同源浏览器 / 非浏览器客户端）→ 放行。
    """
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site == "cross-site":
        raise CsrfError()
    origin = request.headers.get("origin")
    if origin is not None:
        allowed = get_settings().csrf_allowed_origin_list
        if origin not in allowed:
            raise CsrfError()


@router.post("/auth/web/login")
def web_login(
    body: WebLoginRequest,
    service: ServiceDep,
    request: Request,
    response: Response,
) -> dict[str, object]:
    """账号密码登录（同步路由，由框架线程池调度，技术方案 4）。

    refresh 经 HttpOnly Cookie 下发，响应体只含访问令牌。
    """
    pair = service.login_web(body.username, body.password)
    _set_refresh_cookie(response, pair.refresh_token)
    return success(pair.web_view().model_dump(), getattr(request.state, "request_id", None))


@router.post("/auth/wechat/login")
def wechat_login(
    body: WechatLoginRequest,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """微信登录（P2，原生小程序链路）。

    code 换取身份 → 定位/自动建号 → 签发 WECHAT 会话。小程序无 Cookie 语义，
    refresh 随 JSON 体返回。响应绝不含 appid/secret/session_key。
    need_binding=True 表示新会话处于 PRE_BINDING 受限态，前端应引导绑定学生。
    """
    pair, need_binding = service.login_wechat(body.code)
    result = WechatLoginResult(
        access_token=pair.access_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
        need_binding=need_binding,
    )
    return success(result.model_dump(), getattr(request.state, "request_id", None))


@router.post("/auth/refresh")
def refresh(
    service: ServiceDep,
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
) -> dict[str, object]:
    """刷新令牌：轮换刷新凭证并检测重放。

    - Web：从 HttpOnly Cookie 取 refresh，做 CSRF 校验，新凭证重新写入 Cookie，
      响应体只含访问令牌。
    - 原生/小程序：无 Cookie 时从 JSON 体取 refresh，随体返回新凭证。
    """
    settings = get_settings()
    cookie_token = request.cookies.get(settings.refresh_cookie_name)
    if cookie_token:
        _assert_csrf_ok(request)
        pair = service.refresh(cookie_token)
        _set_refresh_cookie(response, pair.refresh_token)
        payload: dict[str, object] = pair.web_view().model_dump()
    elif body and body.refresh_token:
        pair = service.refresh(body.refresh_token)
        payload = pair.model_dump()
    else:
        raise UnauthenticatedError("缺少刷新凭证")
    return success(payload, getattr(request.state, "request_id", None))


@router.post("/auth/logout", status_code=204)
def logout(
    service: ServiceDep,
    session_id: SessionIdDep,
) -> Response:
    """撤销当前会话并清除 Web 端 refresh Cookie。"""
    service.logout(session_id)
    response = Response(status_code=204)
    _clear_refresh_cookie(response)
    return response


@router.get("/me")
def me(
    user: CurrentUserDep,
    request: Request,
) -> dict[str, object]:
    data = CurrentUserResponse.build(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=user.status,
        roles=user.roles,
        permissions=user.permissions,
        pre_binding=user.pre_binding,
    )
    return success(data.model_dump(), getattr(request.state, "request_id", None))


@router.post("/me/student-binding")
def bind_student(
    body: StudentBindingRequest,
    user: CurrentUserDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    sid, sno, name = service.bind_student(
        user.id,
        body.student_no,
        body.binding_code,
        request_id=getattr(request.state, "request_id", None),
    )
    result = StudentBindingResult(student_id=str(sid), student_no=sno, name=name)
    return success(result.model_dump(), getattr(request.state, "request_id", None))


# --------------------------------------------------------------------------- #
# 授权管理闭环（P1 步骤 4）：受限目标选择器 + 角色分配 + 可选权限开关
# --------------------------------------------------------------------------- #
RoleAssignDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.ROLE_ASSIGN.value))
]
OptionalPermManageDep = Annotated[
    CurrentUser,
    Depends(require_permission(PermissionCode.OPTIONAL_PERMISSION_MANAGE.value)),
]


@router.get("/role-assignment-targets")
def role_assignment_targets(
    actor: RoleAssignDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """角色分配目标选择器：返回可管理目标与操作者可授予的角色集合。"""
    items, assignable = service.list_role_assignment_targets(actor.id)
    payload = RoleAssignmentTargetsResponse(
        items=items, assignable_roles=assignable
    )
    return success(payload.model_dump(), getattr(request.state, "request_id", None))


@router.put("/users/{user_id}/roles")
def assign_roles(
    user_id: int,
    body: RoleAssignmentRequest,
    actor: RoleAssignDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """完整替换目标角色集合；差集校验 + 乐观并发，返回实际角色与新版本。"""
    rid = getattr(request.state, "request_id", None)
    roles, version = service.assign_roles(
        actor_user_id=actor.id,
        target_user_id=user_id,
        desired_codes=body.roles,
        expected_version=body.lock_version,
        reason=body.reason,
        request_id=rid,
    )
    result = RoleAssignmentResult(roles=roles, lock_version=version)
    return success(result.model_dump(), rid)


@router.get("/optional-permission-targets")
def optional_permission_targets(
    actor: OptionalPermManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """可选权限目标选择器：仅返回负责人及其三项可选权限当前状态。"""
    items, configurable = service.list_optional_permission_targets(actor.id)
    payload = OptionalPermissionTargetsResponse(
        items=items, configurable_codes=configurable
    )
    return success(payload.model_dump(), getattr(request.state, "request_id", None))


@router.put("/users/{user_id}/optional-permissions/{code}")
def set_optional_permission(
    user_id: int,
    code: str,
    body: OptionalPermissionUpdate,
    actor: OptionalPermManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """逐人开关学生工作负责人可选权限（三项清单，禁自我提权）。"""
    rid = getattr(request.state, "request_id", None)
    code_out, enabled, version = service.set_optional_permission(
        actor_user_id=actor.id,
        target_user_id=user_id,
        code=code,
        enabled=body.enabled,
        expected_version=body.lock_version,
        reason=body.reason,
        request_id=rid,
    )
    result = OptionalPermissionResult(
        code=code_out, enabled=enabled, lock_version=version
    )
    return success(result.model_dump(), rid)


# --------------------------------------------------------------------------- #
# 绑定码管理与换绑（P2-D）：identity.binding.manage 守卫
# --------------------------------------------------------------------------- #
BindingManageDep = Annotated[
    CurrentUser,
    Depends(require_permission(PermissionCode.IDENTITY_BINDING_MANAGE.value)),
]


@router.post("/students/{student_id}/binding-tokens")
def issue_binding_token(
    student_id: int,
    body: BindingTokenIssueRequest,
    actor: BindingManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """为指定学生签发一次性绑定码；明文仅此响应一次，库中只存摘要。"""
    rid = getattr(request.state, "request_id", None)
    token_id, code, expires_at = service.issue_binding_token(
        actor_user_id=actor.id,
        student_id=student_id,
        reason=body.reason,
        request_id=rid,
    )
    result = BindingTokenIssueResult(
        token_id=str(token_id),
        student_id=str(student_id),
        plaintext_code=code,
        expires_at=expires_at.isoformat(),
    )
    return success(result.model_dump(), rid)


@router.post("/binding-tokens/{token_id}/revoke")
def revoke_binding_token(
    token_id: int,
    body: BindingTokenRevokeRequest,
    actor: BindingManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """作废未使用的绑定码；已核销 409，已作废幂等。"""
    rid = getattr(request.state, "request_id", None)
    service.revoke_binding_token(
        actor_user_id=actor.id,
        token_id=token_id,
        reason=body.reason,
        request_id=rid,
    )
    return success({"token_id": str(token_id)}, rid)


@router.post("/users/{user_id}/student-binding-reset")
def student_binding_reset(
    user_id: int,
    body: StudentBindingResetRequest,
    actor: BindingManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """换绑/解绑（线下核验后执行）：改绑或清除绑定，并撤销该账号旧会话。"""
    rid = getattr(request.state, "request_id", None)
    uid, sid, revoked, version = service.student_binding_reset(
        actor_user_id=actor.id,
        target_user_id=user_id,
        new_student_no=body.new_student_no,
        reason=body.reason,
        request_id=rid,
    )
    result = StudentBindingResetResult(
        user_id=str(uid),
        student_id=(str(sid) if sid is not None else None),
        revoked_sessions=revoked,
        lock_version=version,
    )
    return success(result.model_dump(), rid)
