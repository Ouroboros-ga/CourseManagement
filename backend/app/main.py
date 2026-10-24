"""FastAPI 应用组装与路由注册入口。

main.py 只负责应用装配，不放业务流程（技术方案第 5 节）。
业务模块 router 在阶段 1+ 逐步 include 进来。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import fastapi.encoders
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.database import iso_utc
from app.core.exceptions import AppError
from app.core.logging import get_logger, setup_logging

fastapi.encoders.ENCODERS_BY_TYPE[datetime] = iso_utc
BaseModel.model_config = ConfigDict(json_encoders={datetime: iso_utc})
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.modules.academic.enrollment_router import router as enrollment_router
from app.modules.academic.export_router import router as course_export_router
from app.modules.academic.publication_router import router as academic_publication_router
from app.modules.academic.router import router as academic_router
from app.modules.academic.scoped_router import router as scoped_academic_router
from app.modules.attendance.router import router as attendance_router
from app.modules.attendance.scoped_router import router as scoped_attendance_router
from app.modules.audit.router import router as audit_router
from app.modules.file.router import router as file_router
from app.modules.identity.account_router import router as account_router
from app.modules.identity.router import router as identity_router
from app.modules.importer.router import router as importer_router
from app.modules.inspection.router import router as inspection_router
from app.modules.objection.router import router as objection_router
from app.modules.objection.scoped_router import router as scoped_objection_router
from app.modules.organization.router import router as campus_router
from app.modules.report.listing import router as report_listing_router
from app.modules.report.router import router as report_router
from app.modules.timetable.router import router as personal_timetable_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    logger.info("应用启动", extra={"env": settings.app_env})
    # 说明：V1.0 不在每个服务进程启动时抢跑数据库迁移，迁移由单独发布步骤执行。
    mcp_server = getattr(app.state, "agent_mcp_server", None)
    if mcp_server is not None:
        async with mcp_server.session_manager.run():
            yield
    else:
        yield
    logger.info("应用关闭")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="查课管理系统 API",
        version="0.1.0",
        # 生产不暴露交互文档与 schema：docs_url 与 openapi_url 必须同时关闭，
        # 只关 docs 时 /openapi.json 仍会返回完整接口定义（不能只依赖 nginx 遮挡）。
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    # 安全头是应用层兜底；生产由 nginx 统一输出同名头，避免依赖单点配置。
    app.add_middleware(SecurityHeadersMiddleware, is_prod=settings.is_prod)

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
    from app.modules.identity.scoped_router import router as scoped_identity_router
    app.include_router(scoped_identity_router, prefix="/api/v1")
    app.include_router(account_router, prefix="/api/v1")
    app.include_router(campus_router, prefix="/api/v1")
    from app.modules.organization.overview_router import router as overview_router
    app.include_router(overview_router, prefix="/api/v1")
    from app.modules.academic.school_time_router import router as school_time_router
    app.include_router(school_time_router, prefix="/api/v1")
    from app.modules.report.summary_router import router as summary_router
    app.include_router(summary_router, prefix="/api/v1")
    from app.modules.inspection.group_transfer import router as task_group_transfer_router
    app.include_router(task_group_transfer_router, prefix="/api/v1")

    # 基础数据路由（阶段 3）：学期/节次/校历/行政班/学生/课程/教学班/课表/志愿者资格。
    app.include_router(academic_router, prefix="/api/v1/academic")
    from app.modules.academic.scoped_write_router import router as scoped_write_router
    app.include_router(scoped_write_router, prefix="/api/v1")
    app.include_router(academic_publication_router, prefix="/api/v1")
    from app.modules.academic.time_router import router as college_time_router
    app.include_router(college_time_router, prefix="/api/v1")
    from app.modules.academic.semester_defaults_router import router as semester_defaults_router
    app.include_router(semester_defaults_router, prefix="/api/v1")
    from app.modules.academic.offering_router import router as offering_router
    app.include_router(offering_router, prefix="/api/v1")
    from app.modules.academic.management_router import router as academic_management_router
    app.include_router(academic_management_router, prefix="/api/v1")
    from app.modules.academic.staff_router import router as college_staff_router
    app.include_router(college_staff_router, prefix="/api/v1")
    from app.modules.inspection.group_router import router as group_inspection_router
    from app.modules.volunteer.member_router import router as member_router
    app.include_router(member_router, prefix="/api/v1")
    from app.modules.volunteer.management_router import router as organization_management_router
    app.include_router(organization_management_router, prefix="/api/v1")
    app.include_router(group_inspection_router, prefix="/api/v1")
    app.include_router(personal_timetable_router, prefix="/api/v1")
    app.include_router(scoped_attendance_router, prefix="/api/v1")
    app.include_router(scoped_objection_router, prefix="/api/v1")
    from app.modules.objection.precheck_router import router as precheck_management_router
    app.include_router(precheck_management_router, prefix="/api/v1")
    app.include_router(enrollment_router, prefix="/api/v1/academic")
    from app.modules.academic.scoped_enrollment_router import router as scoped_enrollment_router
    app.include_router(scoped_enrollment_router, prefix="/api/v1")
    app.include_router(course_export_router, prefix="/api/v1")
    from app.modules.academic.export_router import scoped_router as scoped_course_export_router
    app.include_router(scoped_course_export_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    from app.modules.audit.scoped_router import router as scoped_audit_router
    app.include_router(scoped_audit_router, prefix="/api/v1")

    # 导入路由（阶段 3）：名单/课表/志愿者资格的预览→确认两步原子导入。
    app.include_router(importer_router, prefix="/api/v1")
    # Literal confirmation-set paths must precede /imports/{batch_id}/confirm.
    from app.modules.importer.confirmation_router import router as confirmation_router
    app.include_router(confirmation_router, prefix="/api/v1")
    from app.modules.importer.intake_router import router as intake_router
    app.include_router(intake_router, prefix="/api/v1")
    from app.modules.importer.scoped_router import router as scoped_importer_router
    app.include_router(scoped_importer_router, prefix="/api/v1")

    # 查课任务与排班路由（阶段 4）：任务预览/生成、列表/详情/本人任务、名单读取。
    app.include_router(inspection_router, prefix="/api/v1")
    from app.modules.inspection.scoped_router import router as scoped_inspection_router
    app.include_router(scoped_inspection_router, prefix="/api/v1")
    from app.modules.inspection.staff_record_router import router as staff_record_router
    app.include_router(staff_record_router, prefix="/api/v1")
    from app.modules.academic.occurrence_location_router import (
        router as occurrence_location_router,
    )
    app.include_router(occurrence_location_router, prefix="/api/v1")

    # 文件路由（阶段 5）：受限上传、短时签名访问与验签下载（技术方案 16）。
    app.include_router(file_router, prefix="/api/v1")

    # 考勤路由（阶段 5）：当前考勤与历史认定读取（按数据范围）、最终考勤更正（技术方案 14）。
    app.include_router(attendance_router, prefix="/api/v1")
    from app.modules.attendance.staff_router import router as staff_attendance_router
    app.include_router(staff_attendance_router, prefix="/api/v1")

    # 异议路由（阶段 6）：学生对本人考勤提异议、初核/终审与终审更正考勤（技术方案 14）。
    app.include_router(objection_router, prefix="/api/v1")
    from app.modules.objection.staff_router import router as staff_objection_router
    app.include_router(staff_objection_router, prefix="/api/v1")

    # 统计路由（阶段 7 W7a）：只读考勤统计与未完成清单（技术方案 17）。周报生成归后续波次。
    app.include_router(report_router, prefix="/api/v1")
    app.include_router(report_listing_router, prefix="/api/v1")
    from app.modules.report.scoped_router import router as scoped_report_router
    app.include_router(scoped_report_router, prefix="/api/v1")

    # Literal academic endpoints must precede the generic /{kind}/{rid} reader.
    app.include_router(scoped_academic_router, prefix="/api/v1")

    if settings.agent_tools_enabled:
        from app.modules.agent.conversation_router import router as agent_conversations_router
        from app.modules.agent.http_router import router as agent_tools_router
        from app.modules.agent.task_router import router as agent_tasks_router

        app.include_router(agent_tools_router, prefix="/api/v1")
        app.include_router(agent_tasks_router, prefix="/api/v1")
        app.include_router(agent_conversations_router, prefix="/api/v1")
        if settings.agent_import_workspace_enabled:
            from app.modules.agent.import_workspace_router import (
                router as agent_import_workspace_router,
            )

            app.include_router(agent_import_workspace_router, prefix="/api/v1")
        if settings.agent_mcp_enabled:
            from app.modules.agent.mcp_adapter import create_mcp_app

            mcp_app, mcp_server = create_mcp_app()
            app.state.agent_mcp_server = mcp_server
            app.mount("/mcp", mcp_app)

    return app


app = create_app()
