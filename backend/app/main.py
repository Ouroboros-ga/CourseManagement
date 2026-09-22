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
from app.modules.academic.router import router as academic_router
from app.modules.attendance.router import router as attendance_router
from app.modules.file.router import router as file_router
from app.modules.identity.router import router as identity_router
from app.modules.importer.router import router as importer_router
from app.modules.inspection.router import router as inspection_router
from app.modules.objection.router import router as objection_router
from app.modules.report.router import router as report_router

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

    # 基础数据路由（阶段 3）：学期/节次/校历/行政班/学生/课程/教学班/课表/志愿者资格。
    app.include_router(academic_router, prefix="/api/v1/academic")

    # 导入路由（阶段 3）：名单/课表/志愿者资格的预览→确认两步原子导入。
    app.include_router(importer_router, prefix="/api/v1")

    # 查课任务与排班路由（阶段 4）：任务预览/生成、列表/详情/本人任务、名单读取。
    app.include_router(inspection_router, prefix="/api/v1")

    # 文件路由（阶段 5）：受限上传、短时签名访问与验签下载（技术方案 16）。
    app.include_router(file_router, prefix="/api/v1")

    # 考勤路由（阶段 5）：当前考勤与历史认定读取（按数据范围）、最终考勤更正（技术方案 14）。
    app.include_router(attendance_router, prefix="/api/v1")

    # 异议路由（阶段 6）：学生对本人考勤提异议、初核/终审与终审更正考勤（技术方案 14）。
    app.include_router(objection_router, prefix="/api/v1")

    # 统计路由（阶段 7 W7a）：只读考勤统计与未完成清单（技术方案 17）。周报生成归后续波次。
    app.include_router(report_router, prefix="/api/v1")

    return app


app = create_app()
