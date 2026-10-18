"""中间件：请求关联 ID 与基线安全响应头。

requestId 贯穿错误体与日志，便于问题追踪与审计关联。

安全头在 nginx 侧也配置同一组（生产入口是 nginx）；此处的实现保证应用在直连、
本地调试或 nginx 配置回退时仍具备基线防护，属纵深防御而非替代部署层配置。
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-Id"

# Swagger UI / ReDoc 依赖 CDN 脚本与内联样式，严格 CSP 会让它们白屏；
# 这些路径只在非生产开放，因此单独跳过 CSP。
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """补齐基线安全响应头（CWE-693）。

    用 `setdefault` 而不是赋值：若下游（如文件下载路由）已设置更严格的策略，
    保留更严格的那个。

    刻意不设置 `Cross-Origin-Embedder-Policy: require-corp`：它会让未声明 CORP
    的第三方资源（Google Fonts、微信头像域名）加载失败，收益不足以抵消破坏面。
    """

    def __init__(self, app: ASGIApp, *, is_prod: bool) -> None:
        super().__init__(app)
        self._is_prod = is_prod

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # HSTS 只在生产 HTTPS 入口下发；本地 http 调试带上会在浏览器里锁定域名。
        if self._is_prod:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        # 非生产环境的文档页依赖 CDN 脚本与内联样式，严格 CSP 会让它们白屏；
        # 生产已关闭文档路由，因此对所有响应（含 404）一律下发严格 CSP。
        skip_csp = not self._is_prod and request.url.path.startswith(_DOC_PATHS)
        if not skip_csp:
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'none'",
            )
        return response
