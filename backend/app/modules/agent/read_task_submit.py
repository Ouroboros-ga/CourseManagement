"""Trusted run identity admits only named read tasks; no model-selected execution identity."""

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.agent.models import AgentRun
from app.modules.agent.run_context import RunContext
from app.modules.agent.schemas import ReadTaskSubmitQuery, ReportExportQuery
from app.modules.agent.task_service import TaskService

PAGES = {
    "report_attendance_export_prepare": "/dashboard/reports?assistant_task_id=",
    "import_preview_review": "/dashboard/academic?tab=imports&assistant_task_id=",
}


def submit_read_task(db: Session, context: RunContext, query: ReadTaskSubmitQuery) -> dict:
    settings = get_settings()
    run = db.get(AgentRun, int(context.run_id))
    if run is None or run.source_session_id is None:
        raise NotFoundError("交互运行不存在")
    if (
        isinstance(query.arguments, ReportExportQuery)
        and context.semester_id is not None
        and int(query.arguments.semester_id) != context.semester_id
    ):
        raise PermissionDeniedError("学期与本次运行不一致")
    service = TaskService(db, settings.agent_tool_connections, environment=settings.app_env)
    task = service.submit(
        int(context.run_id),
        context.actor.id,
        run.source_session_id,
        query.tool_name,
        query.arguments.model_dump(mode="json"),
        f"run_{context.run_id}_{query.request_key}",
    )
    db.commit()
    return task_handoff(task, query.tool_name)


def task_handoff(task, tool_name: str) -> dict:
    return {
        "kind": "TASK_HANDOFF",
        "task_id": str(task.id),
        "task_status": task.status,
        "open_path": f"{PAGES[tool_name]}{task.id}",
        "requires_login": True,
        "business_data_applied": False,
        "message": "任务已登记，处理状态以任务查询结果为准。打开页面后仍需本人核对或下载。",
    }
