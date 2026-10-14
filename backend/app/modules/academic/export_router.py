"""独立课表导出路由，装配时挂 /api/v1。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.academic.export_service import XLSX_CONTENT_TYPE, CourseScheduleExportService
from app.modules.academic.router import guard_legacy_academic
from app.modules.identity.deps import CurrentUser, require_permission
from app.modules.academic.scoped_router import require_scoped_academic_enabled
from app.modules.organization.router import require_campus_enabled

router = APIRouter(tags=["academic"], dependencies=[Depends(guard_legacy_academic)])
ExportDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.COURSE_SCHEDULE_EXPORT.value))
]
scoped_router = APIRouter(tags=["college-academic-export"], dependencies=[
    Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)])


@scoped_router.get("/colleges/{cid}/course-schedules/export")
def export_college_schedules(cid: Annotated[int, Path(gt=0, le=2**63 - 1)], actor: ExportDep,
                            db: Annotated[Session, Depends(get_db)],
                            semester_id: Annotated[int, Query(gt=0, le=2**63 - 1)],
                            teaching_class_ids: Annotated[list[int] | None, Query(max_length=500)] = None):
    content = CourseScheduleExportService(db, college_id=cid).export(actor.id, semester_id, teaching_class_ids)
    return Response(content=content, media_type=XLSX_CONTENT_TYPE,
                    headers={"Content-Disposition": 'attachment; filename="college-course-schedules.xlsx"'})


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
