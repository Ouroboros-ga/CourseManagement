"""Prepare a fixed same-origin export action; original REST remains the generation boundary."""

from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import PermissionDeniedError
from app.modules.agent.run_context import RunContext
from app.modules.agent.schemas import ReportExportQuery
from app.modules.identity.resource_scope import resolve_scope
from app.modules.report.schemas import AttendanceStatsQuery
from app.modules.report.service import StatisticsService

FORMATS = {
    "ANALYTICS_XLSX": ("export", "考勤统计表（Excel）"),
    "DETAIL_DOCX": ("export-detail-doc", "考勤明细（Word）"),
    "STUDY_XLSX": ("export-study-excel", "学风考勤表（Excel）"),
}


def prepare_export(db: Session, context: RunContext, query: ReportExportQuery) -> dict:
    settings = get_settings()
    if (
        context.college_id is None
        or not settings.campus_business_scoped_enabled
        or not settings.campus_configuration_enabled
    ):
        raise PermissionDeniedError("学院统计导出尚未启用")
    resolve_scope(db, context.actor, context.college_id, "statistics.read")
    window = query.model_dump(exclude={"format"})
    result = StatisticsService(db, college_id=context.college_id).attendance_stats(
        context.actor,
        AttendanceStatsQuery(**window),
        include_tasks=False,
    )
    suffix, title = FORMATS[query.format]
    params = query.model_dump(mode="json", exclude={"format"}, exclude_none=True)
    path = (
        f"/api/v1/colleges/{context.college_id}/statistics/attendance/{suffix}"
        f"?{urlencode(params)}"
    )
    return {
        "kind": "ATTENDANCE_REPORT_DOWNLOAD",
        "artifact_status": "NOT_GENERATED",
        "format": query.format,
        "title": title,
        "message": "已准备导出，点击下载后按当前权限和数据生成文件。",
        "college_id": str(context.college_id),
        "window": params,
        "matching_task_count": result.eligible_task_count,
        "download": {"method": "GET", "path": path, "requires_login": True},
    }
