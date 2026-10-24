import json
import logging
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode, NotFoundError, PermissionDeniedError
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.run_context import RunContext
from app.modules.agent.schemas import (
    ImportReviewQuery,
    ReadTaskSubmitQuery,
    ReportExportQuery,
    ResponsibilityQuery,
    SelfAttendanceQuery,
    SummaryQuery,
    TaskStatusQuery,
    TimetableQuery,
    ToolResult,
)

logger = logging.getLogger(__name__)


def invoke_tool(db: Session, context: RunContext, name: str, arguments: dict) -> ToolResult:
    registry = ToolRegistry()
    try:
        spec = registry.get(name)
    except KeyError:
        raise NotFoundError("工具不存在") from None
    if context.entry_kind not in spec.entry_kinds or context.workflow_kind != spec.workflow_kind:
        raise NotFoundError("工具不存在")
    try:
        query = spec.input_model.model_validate(arguments)
    except ValidationError as error:
        # Pydantic errors include raw inputs; do not echo identity or secret fields.
        raise AppError(ErrorCode.VALIDATION_ERROR, "工具参数不符合合同", 422) from error
    if (
        isinstance(query, TimetableQuery)
        and context.semester_id is not None
        and int(query.semester_id) != context.semester_id
    ):
        raise PermissionDeniedError("学期与本次运行不一致")
    trace_id = uuid4().hex
    data: dict[str, Any]
    if name in {"objection_case_get", "objection_material_access", "objection_precheck_save"}:
        from app.modules.agent.objection_runtime import invoke_objection

        data = invoke_objection(db, context, name, query)
    elif name in {"change_prepare", "change_apply"}:
        from app.modules.agent.change_runtime import invoke_change

        data = invoke_change(db, context, name)
    elif name == "system_probe":
        data = {"contract_version": "v1"}
    elif name == "task_status_get":
        from app.modules.agent.task_service import TaskService

        assert isinstance(query, TaskStatusQuery)
        settings = get_settings()
        data = TaskService(db, settings.agent_tool_connections, environment=settings.app_env).read(
            int(query.task_id), context.actor.id, run_id=int(context.run_id)
        )
    elif name == "self_attendance_list":
        assert isinstance(query, SelfAttendanceQuery)
        from app.modules.attendance.service import AttendanceService

        data = AttendanceService(db).list_my_attendance(
            context.actor,
            PageParams(query.page, query.page_size),
            task_id=int(query.task_id) if query.task_id else None,
            effective_type=query.effective_type,
        )
    elif name == "self_timetable_get":
        assert isinstance(query, TimetableQuery)
        from app.modules.timetable.service import PersonalTimetableService

        data = PersonalTimetableService(db, context.actor.id).get(int(query.semester_id))
    elif name == "read_task_submit":
        from app.modules.agent.read_task_submit import submit_read_task

        assert isinstance(query, ReadTaskSubmitQuery)
        data = submit_read_task(db, context, query)
    elif name == "import_preview_review":
        from app.modules.agent.import_review import review_previews

        assert isinstance(query, ImportReviewQuery)
        data = review_previews(db, context, query)
    elif name == "report_attendance_export_prepare":
        from app.modules.agent.report_export import prepare_export

        assert isinstance(query, ReportExportQuery)
        data = prepare_export(db, context, query)
    elif name == "report_attendance_summary":
        assert isinstance(query, SummaryQuery)
        from app.modules.identity.resource_scope import resolve_scope
        from app.modules.report.schemas import AttendanceStatsQuery
        from app.modules.report.service import StatisticsService

        if context.college_id is None or not get_settings().campus_business_scoped_enabled:
            raise PermissionDeniedError("学院业务范围尚未启用")
        resolve_scope(db, context.actor, context.college_id, "statistics.read")
        result = StatisticsService(db, college_id=context.college_id).attendance_stats(
            context.actor,
            AttendanceStatsQuery(**query.model_dump()),
            include_tasks=False,
        )
        # The assistant needs totals, not staff contacts or the full class inventory.
        data = {
            "overall": result.overall.model_dump(),
            "eligible_task_count": result.eligible_task_count,
        }
    elif name == "responsibility_tasks_list":
        from app.modules.inspection.scoped_service import ScopedInspectionService

        assert isinstance(query, ResponsibilityQuery)
        if context.college_id is None or not get_settings().campus_business_scoped_enabled:
            raise PermissionDeniedError("学院业务范围尚未启用")
        data = ScopedInspectionService(db, context.actor, context.college_id).list_tasks(
            context.actor,
            PageParams(query.page, query.page_size),
            semester_id=int(query.semester_id),
            week_no=query.week_no,
            inspection_date=None,
            inspection_type=None,
            include_canceled=False,
        )
    else:
        raise NotFoundError("工具不存在")
    encoded = jsonable_encoder(data)
    if len(json.dumps(encoded, ensure_ascii=False).encode()) > 128 * 1024:
        raise AppError(ErrorCode.VALIDATION_ERROR, "结果过大，请缩小查询范围", 422)
    tool_result = ToolResult(
        status="MANUAL_REQUIRED" if data.get("status") == "MANUAL_REQUIRED" else "SUCCEEDED",
        data=encoded,
        trace_id=trace_id,
    )
    logger.info(
        "agent_tool_result",
        extra={
            "tool": name,
            "run_id": context.run_id,
            "trace_id": trace_id,
            "status": tool_result.status,
        },
    )
    return tool_result
