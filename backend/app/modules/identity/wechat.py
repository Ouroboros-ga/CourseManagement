"""微信登录 code2session 客户端抽象（技术方案 P2、PERMISSIONS.md 16）。

职责边界：
- 只做"临时登录凭证 code → openid"的一次出站换取，不写库、不做授权判断。
- 以 appid + openid 唯一识别微信身份；session_key 只在进程内瞬时持有，
  绝不进入响应、审计、日志或持久层。
- 出站失败（网络/超时/上游错误码/响应不可解析）统一映射为可预期的 AppError，
  让登录链路对"错误/超时"有确定语义（P2 出口要求）。

真实实现用 httpx（已提升为运行时依赖）；测试注入 Mock 实现，覆盖成功/错误/超时，
无需真实微信服务器。客户端不读取全局 Settings，构造参数由服务层显式传入，便于替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.exceptions import AppError, ErrorCode, UnauthenticatedError


@dataclass(frozen=True)
class WechatLoginOutcome:
    """换取成功结果。session_key 仅供进程内使用，禁止外泄。"""

    openid: str
    session_key: str


# 明确的"凭证类"错误码：微信侧判定 code 非法/已用，属客户端可纠正的登录失败。
_INVALID_CODE_ERRCODES: frozenset[int] = frozenset({40029, 40163})
# 其余已知非致命错误统一按上游不可用处理（限流、系统繁忙、appid 配置错误等）。


class WechatCode2SessionClient(Protocol):
    """code2session 交换接口。实现方负责把 code 换成 openid 或抛出映射后的错误。"""

    def exchange(self, code: str) -> WechatLoginOutcome:
        ...


class HttpxWechatCode2SessionClient:
    """生产实现：GET jscode2session，解析 openid/session_key。"""

    def __init__(
        self,
        *,
        appid: str,
        secret: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._appid = appid
        self._secret = secret
        self._base_url = base_url
        self._timeout = timeout_seconds

    def exchange(self, code: str) -> WechatLoginOutcome:
        params = {
            "appid": self._appid,
            "secret": self._secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        try:
            resp = httpx.get(self._base_url, params=params, timeout=self._timeout)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            # 超时 / 连接错误：上游暂不可用，交由调用方稍后重试。
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信服务暂时不可用，请稍后重试",
                http_status=502,
            ) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信登录响应格式异常",
                http_status=502,
            ) from exc
        if not isinstance(data, dict):
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信登录响应格式异常",
                http_status=502,
            )

        errcode = data.get("errcode", 0)
        # errcode 可能缺省或为 0；非 0 视为失败。
        try:
            errcode_int = int(errcode)
        except (TypeError, ValueError):
            errcode_int = -1
        if errcode_int != 0:
            if errcode_int in _INVALID_CODE_ERRCODES:
                # 凭证非法/已被使用：登录失败语义，不泄露上游细节。
                raise UnauthenticatedError("微信登录凭证无效，请重新进入小程序")
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信登录暂时失败，请稍后重试",
                http_status=502,
            )

        openid = data.get("openid")
        if not isinstance(openid, str) or not openid:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信登录未返回有效身份",
                http_status=502,
            )
        session_key = data.get("session_key") or ""
        return WechatLoginOutcome(
            openid=openid,
            session_key=session_key if isinstance(session_key, str) else "",
        )


class MockWechatCode2SessionClient:
    """测试替身：按预置映射把 code 换成 openid，或模拟错误/超时。

    - code_to_openid：显式映射；未命中时按 code 派生稳定 openid（同一 code 幂等）。
    - invalid_codes：模拟"凭证无效"（映射为 401 Unauthenticated）。
    - timeout_codes：模拟网络/超时（映射为 502 UPSTREAM_UNAVAILABLE）。
    - upstream_error_codes：模拟非凭证类上游错误（映射为 502）。
    """

    def __init__(
        self,
        *,
        code_to_openid: dict[str, str] | None = None,
        invalid_codes: set[str] | None = None,
        timeout_codes: set[str] | None = None,
        upstream_error_codes: set[str] | None = None,
    ) -> None:
        self._map = code_to_openid or {}
        self._invalid = invalid_codes or set()
        self._timeout = timeout_codes or set()
        self._upstream_error = upstream_error_codes or set()

    def exchange(self, code: str) -> WechatLoginOutcome:
        if code in self._timeout:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信服务暂时不可用，请稍后重试",
                http_status=502,
            )
        if code in self._invalid:
            raise UnauthenticatedError("微信登录凭证无效，请重新进入小程序")
        if code in self._upstream_error:
            raise AppError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "微信登录暂时失败，请稍后重试",
                http_status=502,
            )
        openid = self._map.get(code) or f"mock_openid_{code}"
        return WechatLoginOutcome(openid=openid, session_key="mock_session_key")


def build_default_client() -> WechatCode2SessionClient:
    """按当前配置构造生产客户端（供服务层在无注入时回退使用）。"""

    from app.core.config import get_settings

    settings = get_settings()
    return HttpxWechatCode2SessionClient(
        appid=settings.wechat_appid,
        secret=settings.wechat_secret,
        base_url=settings.wechat_code2session_url,
        timeout_seconds=settings.wechat_timeout_seconds,
    )
