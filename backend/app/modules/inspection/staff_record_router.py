"""教职工只读卡片、明细、统计与导出路由。

遵循原则：
- 静态子路由 summary/export 必须在动态 {task_id} 之前注册；
- view=teaching/responsible 显式收窄；
- 所有对外 ID 均使用字符串序列化返回；
- 失败/未授权按标准错误结构统一处理。
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.common.responses import success
from app.core.database import get_db
from app.modules.identity.deps import get_current_user
from app.modules.identity.service import CurrentUser
from app.modules.inspection.staff_record_query import StaffRecordQueryService
from app.modules.inspection.staff_record_schemas import ViewLiteral
from app.modules.report.staff_export import XLSX_CONTENT_TYPE

router = APIRouter(tags=["staff-records"])


@router.get("/me/inspection-records/summary")
def get_inspection_records_summary(
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
    semester_id: int | None = Query(None, description="学期 ID"),
    inspection_date: date | None = Query(None, description="查课日期"),
    date_from: date | None = Query(None, description="起始日期"),
    date_to: date | None = Query(None, description="截止日期"),
    teaching_class_id: int | None = Query(None, description="教学班 ID"),
    administrative_class_id: int | None = Query(None, description="行政班 ID"),
    responsible_college_id: int | None = Query(None, description="任务负责学院 ID"),
    course_name: str | None = Query(None, description="课程名称"),
    actor: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = StaffRecordQueryService(db, actor)
    res = service.get_summary(
        view,
        semester_id=semester_id,
        inspection_date=inspection_date,
        date_from=date_from,
        date_to=date_to,
        teaching_class_id=teaching_class_id,
        administrative_class_id=administrative_class_id,
        responsible_college_id=responsible_college_id,
        course_name=course_name,
    )
    return success(res.model_dump())


@router.get("/me/inspection-records/export")
def export_inspection_records(
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
    semester_id: int | None = Query(None, description="学期 ID"),
    inspection_date: date | None = Query(None, description="查课日期"),
    date_from: date | None = Query(None, description="起始日期"),
    date_to: date | None = Query(None, description="截止日期"),
    teaching_class_id: int | None = Query(None, description="教学班 ID"),
    administrative_class_id: int | None = Query(None, description="行政班 ID"),
    responsible_college_id: int | None = Query(None, description="任务负责学院 ID"),
    course_name: str | None = Query(None, description="课程名称"),
    actor: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = StaffRecordQueryService(db, actor)
    content, filename = service.export_excel(
        view,
        semester_id=semester_id,
        inspection_date=inspection_date,
        date_from=date_from,
        date_to=date_to,
        teaching_class_id=teaching_class_id,
        administrative_class_id=administrative_class_id,
        responsible_college_id=responsible_college_id,
        course_name=course_name,
    )
    encoded_filename = quote(filename)
    return Response(
        content=content,
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/me/inspection-records")
def list_inspection_records(
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
    semester_id: int | None = Query(None, description="学期 ID"),
    inspection_date: date | None = Query(None, description="查课日期"),
    date_from: date | None = Query(None, description="起始日期"),
    date_to: date | None = Query(None, description="截止日期"),
    teaching_class_id: int | None = Query(None, description="教学班 ID"),
    administrative_class_id: int | None = Query(None, description="行政班 ID"),
    responsible_college_id: int | None = Query(None, description="任务负责学院 ID"),
    course_name: str | None = Query(None, description="课程名称"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    actor: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = StaffRecordQueryService(db, actor)
    items, total = service.list_cards(
        view,
        PageParams(page=page, page_size=page_size),
        semester_id=semester_id,
        inspection_date=inspection_date,
        date_from=date_from,
        date_to=date_to,
        teaching_class_id=teaching_class_id,
        administrative_class_id=administrative_class_id,
        responsible_college_id=responsible_college_id,
        course_name=course_name,
    )
    return success(
        {
            "items": [it.model_dump() for it in items],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    )


@router.get("/me/inspection-records/{task_id}")
def get_inspection_record(
    task_id: int,
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
    actor: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = StaffRecordQueryService(db, actor)
    card = service.get_card(task_id, view)
    return success(card.model_dump())


@router.get("/me/inspection-records/{task_id}/attendance")
def list_task_student_attendance(
    task_id: int,
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
    effective_type: str | None = Query(None, description="考勤认定类型"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    actor: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = StaffRecordQueryService(db, actor)
    items, total = service.list_attendance(
        task_id,
        view,
        effective_type=effective_type,
        params=PageParams(page=page, page_size=page_size),
    )
    return success(
        {
            "items": [it.model_dump() for it in items],
            "total": total,
            "page": page,
            "pageSize": page_size,
        }
    )


__all__ = ["router"]
