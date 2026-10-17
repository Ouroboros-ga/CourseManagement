"""教职工本人授课的真实课次地点读取与变更路由（T04）。

错误码约定：非本人教学班 / 该日无此课次 → 404 NOT_FOUND 防枚举；学期归档、
共享映射漂移/冲突 → 409 STATE_CONFLICT；提供的 revision 过期 → 409
VERSION_CONFLICT。授权完全在服务锁事务内复核，路由不做范围放行。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.occurrence_location import (
    OccurrenceLocationRequest,
    OccurrenceLocationService,
)
from app.modules.identity.staff_deps import CurrentStaffDep

router = APIRouter(tags=["staff-teaching"])


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
