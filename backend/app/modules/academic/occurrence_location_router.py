"""教职工本人的正式课次与课次地点读取/变更路由（T04，审查 F4）。

错误码约定：非本人教学班 / 该日无此课次 → 404 NOT_FOUND 防枚举；学期归档、
共享映射漂移/冲突 → 409 STATE_CONFLICT；提供的 revision 过期 → 409
VERSION_CONFLICT；日期区间非法或过长 → 422。授权完全在服务锁事务内复核，
路由不做范围放行。

``GET /me/teaching-occurrences`` 列出本人在区间内的**正式**课次：查课卡片按任务组织，
没有被抽到的课在卡片里不存在，教师因此无法为那节课改地点；日历直接来自正式课表与校历。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.occurrence_location import (
    OccurrenceLocationRequest,
    OccurrenceLocationService,
)
from app.modules.identity.staff_deps import CurrentStaffDep

router = APIRouter(tags=["staff-teaching"])


@router.get("/me/teaching-occurrences")
def list_my_teaching_occurrences(
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    teaching_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    service = OccurrenceLocationService(db)
    data = service.occurrence_calendar(
        staff,
        date_from=date_from,
        date_to=date_to,
        teaching_class_id=teaching_class_id,
        page=page,
        page_size=page_size,
    )
    return success(asdict(data))


@router.get("/me/teaching-classes/{teaching_class_id}/occurrences/{occurrence_key}/location")
def get_occurrence_location(
    teaching_class_id: int,
    occurrence_key: str,
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
):
    service = OccurrenceLocationService(db)
    return success(asdict(service.location_summary(staff, teaching_class_id, occurrence_key)))


@router.patch("/me/teaching-classes/{teaching_class_id}/occurrences/{occurrence_key}/location")
def change_occurrence_location(
    teaching_class_id: int,
    occurrence_key: str,
    body: OccurrenceLocationRequest,
    request: Request,
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
):
    service = OccurrenceLocationService(db)
    request_id = getattr(request.state, "request_id", None)
    summary = service.change_location(
        staff, teaching_class_id, occurrence_key, body, request_id
    )
    return success(asdict(summary))


__all__ = ["router"]
