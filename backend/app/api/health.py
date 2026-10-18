"""系统健康检查路由：区分存活(liveness)与就绪(readiness)。

- /health/live：仅验证进程存活，不触碰任何外部依赖，供编排器 liveness 探针使用。
- /health/ready：真正探测数据库连接是否可用，供 readiness 探针使用；
  数据库不可用时返回 503，让流量暂时绕开尚未就绪的实例。

探活使用独立短超时连接，不进入业务线程池、不占用请求级 Session。

响应体按环境分级：探针只需要 HTTP 状态码，因此生产只回 `status`/`check`，
不回显 `env`、`database`、异常类型；这些细节在非生产环境保留，便于本地排查。
公开端点回显基础设施状态属于信息泄漏（CWE-200）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["system"])


def _diagnostics_enabled() -> bool:
    """非生产环境才输出运行细节；生产以状态码表达就绪与否。"""
    return not get_settings().is_prod


@router.get("/live")
def live(request: Request) -> dict[str, object]:
    """存活检查：进程在跑即返回 ok，不连数据库。"""
    body: dict[str, object] = {
        "status": "ok",
        "check": "live",
        "requestId": getattr(request.state, "request_id", None),
    }
    if _diagnostics_enabled():
        body["env"] = get_settings().app_env
    return body


@router.get("/ready", response_model=None)
def ready(request: Request) -> dict[str, object] | JSONResponse:
    """就绪检查：执行一次轻量 SELECT 1 验证数据库可连通。

    连接失败时返回 503；异常类型只在非生产环境回显，生产仅记结构化日志
    （不回显密码或连接串，避免把内部拓扑带进公开响应）。
    """
    request_id = getattr(request.state, "request_id", None)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 就绪探针需吞掉任意驱动异常并转 503
        logger.warning("数据库就绪检查失败：%s", type(exc).__name__)
        content: dict[str, object] = {
            "status": "unavailable",
            "check": "ready",
            "requestId": request_id,
        }
        if _diagnostics_enabled():
            content["database"] = "down"
            content["reason"] = type(exc).__name__
        return JSONResponse(status_code=503, content=content)
    body: dict[str, object] = {
        "status": "ok",
        "check": "ready",
        "requestId": request_id,
    }
    if _diagnostics_enabled():
        body["database"] = "up"
        body["env"] = get_settings().app_env
    return body
