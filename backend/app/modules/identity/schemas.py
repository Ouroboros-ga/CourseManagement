"""身份与权限模块的请求/响应模型（Pydantic 2.x）。

响应模型对客户端过滤字段，绝不直接返回 ORM 实体；ID 以字符串对外暴露。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.common.responses import to_id_str


class WebLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """刷新请求体。

    Web 端刷新凭证经 HttpOnly Cookie 传输，请求体可为空（字段省略）；
    小程序等无 Cookie 语义的客户端继续在 JSON 体中携带 refresh_token。
    """

    refresh_token: str | None = Field(
        default=None, min_length=8, max_length=256
    )


class TokenPair(BaseModel):
    """服务端签发的令牌对（内部与原生客户端使用）。

    access：短期访问令牌，客户端内存持有并置于 Authorization 头。
    refresh：不透明刷新凭证——Web 端经 HttpOnly Cookie 下发（见 web_view），
    仅在小程序等原生客户端才随 JSON 体返回。
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str

    def web_view(self) -> AccessTokenResponse:
        """Web 响应体：仅暴露访问令牌，刷新凭证走 Set-Cookie，不出现在此处。"""
        return AccessTokenResponse(
            access_token=self.access_token,
            token_type=self.token_type,
            expires_in=self.expires_in,
        )


class AccessTokenResponse(BaseModel):
    """Web 登录/刷新成功响应体：只含访问令牌；refresh 经 HttpOnly Cookie 下发。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleInfo(BaseModel):
    code: str
    name: str


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str | None
    display_name: str
    status: str
    roles: list[str]
    permissions: list[str]
    binding_required: bool = False

    @classmethod
    def build(
        cls,
        *,
        id: int,
        username: str | None,
        display_name: str,
        status: str,
        roles: list[str],
        permissions: list[str],
        pre_binding: bool = False,
    ) -> CurrentUserResponse:
        return cls(
            id=to_id_str(id),
            username=username,
            display_name=display_name,
            status=status,
            roles=roles,
            permissions=permissions,
            binding_required=pre_binding,
        )


class StudentBindingRequest(BaseModel):
    """学生身份绑定：输入学号与一次性绑定码。"""

    student_no: str = Field(min_length=1, max_length=32)
    binding_code: str = Field(min_length=8, max_length=128)


class StudentBindingResult(BaseModel):
    student_id: str
    student_no: str
    name: str


class OptionalPermissionUpdate(BaseModel):
    """PUT /users/{id}/optional-permissions/{code} 请求体：逐人开关可选权限。

    lockVersion 用于乐观并发（不符 409）；reason 写入审计。code 取自路径。
    """

    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    lock_version: int = Field(alias="lockVersion", ge=0)
    reason: str | None = Field(default=None, max_length=512)


# --------------------------------------------------------------------------- #
# 角色分配 / 可选权限管理闭环（P1 步骤 4）
# --------------------------------------------------------------------------- #
class RoleAssignmentRequest(BaseModel):
    """PUT /users/{id}/roles 请求体。

    - roles：期望的完整角色集合（服务端按增删差集校验，防借省略撤销受保护角色）。
    - lockVersion：客户端读到的目标 lock_version，用于乐观并发；不符则 409。
    - reason：变更理由，写入审计（可空但建议提供）。

    本模型刻意不含口令、状态或权限字段：角色分配是唯一杠杆，账号编辑接口
    （他处）不得接受 roles/permissions，避免绕过此处差集校验（防旁路）。
    """

    model_config = ConfigDict(populate_by_name=True)

    roles: list[str] = Field(default_factory=list)
    lock_version: int = Field(alias="lockVersion", ge=0)
    reason: str | None = Field(default=None, max_length=512)


class RoleAssignmentResult(BaseModel):
    roles: list[str]
    lock_version: int


class OptionalPermissionState(BaseModel):
    code: str
    enabled: bool


class OptionalPermissionResult(BaseModel):
    code: str
    enabled: bool
    lock_version: int


class RoleAssignmentTargetItem(BaseModel):
    id: str
    username: str | None
    display_name: str
    status: str
    roles: list[str]
    lock_version: int


class RoleAssignmentTargetsResponse(BaseModel):
    items: list[RoleAssignmentTargetItem]
    assignable_roles: list[str]


class OptionalPermissionTargetItem(BaseModel):
    id: str
    display_name: str
    status: str
    permissions: list[OptionalPermissionState]
    lock_version: int


class OptionalPermissionTargetsResponse(BaseModel):
    items: list[OptionalPermissionTargetItem]
    configurable_codes: list[str]


# --------------------------------------------------------------------------- #
# 微信登录与学生绑定管理（P2）
# --------------------------------------------------------------------------- #
class WechatLoginRequest(BaseModel):
    """POST /auth/wechat/login：wx.login 得到的临时登录凭证 code。"""

    code: str = Field(min_length=1, max_length=512)


class WechatLoginResult(BaseModel):
    """微信登录结果。

    小程序等原生客户端无 Cookie 语义，refresh 随体返回；need_binding=True 时
    前端应跳转绑定页。绝不包含 session_key / appid / secret 等敏感字段。
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    need_binding: bool


class BindingTokenIssueRequest(BaseModel):
    """POST /students/{id}/binding-tokens：可选签发理由，写入审计。"""

    reason: str | None = Field(default=None, max_length=512)


class BindingTokenIssueResult(BaseModel):
    """一次性绑定码签发结果；明文 code 仅此返回一次。"""

    token_id: str
    student_id: str
    plaintext_code: str
    expires_at: str


class BindingTokenRevokeRequest(BaseModel):
    """POST /binding-tokens/{id}/revoke：作废理由，写入审计。"""

    reason: str | None = Field(default=None, max_length=512)


class StudentBindingResetRequest(BaseModel):
    """POST /users/{id}/student-binding-reset：换绑或解绑（线下核验后执行）。

    new_student_no 提供则换绑到该学号，省略/为 null 表示解除绑定。
    """

    new_student_no: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=512)


class StudentBindingResetResult(BaseModel):
    user_id: str
    student_id: str | None
    revoked_sessions: int
    lock_version: int
