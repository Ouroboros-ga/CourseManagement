"""院级异议列表、详情和一次审核；没有恢复旧初核流程。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.inspection.dimensions import DimensionsDep
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from app.modules.objection.scoped_service import ScopedObjectionService
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    tags=["college-objection"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def get_service(cid: ResourceId, actor: CurrentUserDep, db: Annotated[Session, Depends(get_db)]):
    return ScopedObjectionService(db, actor, cid)


Service = Annotated[ScopedObjectionService, Depends(get_service)]


@router.get("/colleges/{cid}/objections")
def list_objections(
    cid: ResourceId,
    actor: CurrentUserDep,
    service: Service,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    dimensions: DimensionsDep,
    attendance_record_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    final_status: Annotated[str | None, Query(max_length=16)] = None,
    semester_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
):
    return success(
        service.list_objections(
            actor,
            params,
            attendance_record_id=attendance_record_id,
            final_status=final_status,
            initial_status=None,
            semester_id=semester_id,
            dimensions=dimensions,
        ),
        getattr(request.state, "request_id", None),
    )


@router.get("/colleges/{cid}/objections/{rid}")
def get_objection(
    cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: Service, request: Request
):
    return success(
        service.get_objection(actor, rid).model_dump(), getattr(request.state, "request_id", None)
    )


@router.post("/colleges/{cid}/objections/{rid}/review")
def review(
    cid: ResourceId,
    rid: ResourceId,
    body: ObjectionFinalReviewRequest,
    actor: CurrentUserDep,
    service: Service,
    request: Request,
):
    request_id = getattr(request.state, "request_id", None)
    return success(service.final_review(actor, rid, body, request_id).model_dump(), request_id)
