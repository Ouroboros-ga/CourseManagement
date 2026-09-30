"""独立课表导出路由，装配时挂 /api/v1。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.academic.export_service import XLSX_CONTENT_TYPE, CourseScheduleExportService
from app.modules.identity.deps import CurrentUser, require_permission

router = APIRouter(tags=["academic"])
ExportDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.COURSE_SCHEDULE_EXPORT.value))
]


@router.get("/course-schedules/export")
def export_course_schedules(
    actor: ExportDep,
    db: Annotated[Session, Depends(get_db)],
    semester_id: Annotated[int, Query(ge=1)],
    teaching_class_ids: Annotated[list[int] | None, Query(max_length=500)] = None,
) -> Response:
    content = CourseScheduleExportService(db).export(actor.id, semester_id, teaching_class_ids)
    return Response(
        content=content,
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": 'attachment; filename="course-schedules.xlsx"'},
    )
