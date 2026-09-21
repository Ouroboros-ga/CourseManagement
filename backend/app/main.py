"""FastAPI 应用组装与路由注册入口。

main.py 只负责应用装配，不放业务流程（技术方案第 5 节）。
业务模块 router 在阶段 1+ 逐步 include 进来。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestIdMiddleware
from app.modules.identity.router import router as identity_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    logger.info("应用启动", extra={"env": settings.app_env})
    # 说明：V1.0 不在每个服务进程启动时抢跑数据库迁移，迁移由单独发布步骤执行。
    yield
    logger.info("应用关闭")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="查课管理系统 API",
        version="0.1.0",
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)

    if settings.cors_origin_list:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": exc.code.value,
                "message": exc.message,
                "fieldErrors": exc.field_errors,
                "requestId": request_id,
            },
        )

    # 系统健康检查路由：/health/live（存活）与 /health/ready（数据库就绪）。
    app.include_router(health_router)

    # 身份与权限路由（阶段 1）。
    app.include_router(identity_router, prefix="/api/v1")

    return app


app = create_app()
