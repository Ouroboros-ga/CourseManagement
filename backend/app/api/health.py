"""系统健康检查路由：区分存活(liveness)与就绪(readiness)。

- /health/live：仅验证进程存活，不触碰任何外部依赖，供编排器 liveness 探针使用。
- /health/ready：真正探测数据库连接是否可用，供 readiness 探针使用；
  数据库不可用时返回 503，让流量暂时绕开尚未就绪的实例。

探活使用独立短超时连接，不进入业务线程池、不占用请求级 Session。
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


@router.get("/live")
def live(request: Request) -> dict[str, object]:
    """存活检查：进程在跑即返回 ok，不连数据库。"""
    return {
        "status": "ok",
        "check": "live",
        "env": get_settings().app_env,
        "requestId": getattr(request.state, "request_id", None),
    }


@router.get("/ready", response_model=None)
def ready(request: Request) -> dict[str, object] | JSONResponse:
    """就绪检查：执行一次轻量 SELECT 1 验证数据库可连通。

    连接失败时返回 503，并把错误摘要写进响应，便于定位是网络还是凭证问题
    （不回显密码等敏感信息，仅记异常类型与短语）。
    """
    request_id = getattr(request.state, "request_id", None)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 就绪探针需吞掉任意驱动异常并转 503
        logger.warning("数据库就绪检查失败：%s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "check": "ready",
                "database": "down",
                "reason": type(exc).__name__,
                "requestId": request_id,
            },
        )
    return {
        "status": "ok",
        "check": "ready",
        "database": "up",
        "env": get_settings().app_env,
        "requestId": request_id,
    }
