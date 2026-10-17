"""责任班级异议读取与一次审核路由（T05）。

范围完全在服务事务内复核：路由不做任何放行，也不根据客户端提交的学院/班级放宽。
错误口径：不在本人责任范围（含外院任务的改判）→ 404 防枚举；任务确属外院负责 → 403
明确告知需由该学院审核；考勤或异议版本过期 → 409；状态机已完成 → 409。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.modules.identity.staff_deps import CurrentStaffDep
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from app.modules.objection.staff_service import StaffResponsibleObjectionService

router = APIRouter(tags=["staff-objections"])

FinalStatus = Annotated[str | None, Query(max_length=16)]
InitialStatus = Annotated[str | None, Query(max_length=16)]
BoundId = Annotated[int | None, Query(gt=0, le=2**63 - 1)]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/me/responsible-objections")
def list_responsible_objections(
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
    params: Annotated[PageParams, Depends(page_params)],
    request: Request,
    final_status: FinalStatus = None,
    initial_status: InitialStatus = None,
    semester_id: BoundId = None,
    administrative_class_id: BoundId = None,
):
    service = StaffResponsibleObjectionService(db, staff)
    data = service.list_responsible(
        params,
        final_status=final_status,
        initial_status=initial_status,
        semester_id=semester_id,
        administrative_class_id=administrative_class_id,
    )
    return success(
        {**data, "items": [item.model_dump() for item in data["items"]]}, _rid(request)
    )


@router.get("/me/responsible-objections/{objection_id}")
def get_responsible_objection(
    objection_id: int,
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
):
    service = StaffResponsibleObjectionService(db, staff)
    return success(service.get_responsible(objection_id).model_dump(), _rid(request))


@router.post("/me/responsible-objections/{objection_id}/review")
def review_responsible_objection(
    objection_id: int,
    body: ObjectionFinalReviewRequest,
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
):
    service = StaffResponsibleObjectionService(db, staff)
    result = service.review(objection_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


__all__ = ["router"]
