from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError
from app.modules.academic.time_schemas import TimeConfiguration, TimePublish
from app.modules.academic.time_service import CollegeTimeService
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled


def require_scheduling_enabled():
    settings = get_settings()
    if not (
        settings.campus_scheduling_enabled
        and settings.campus_business_scoped_enabled
        and settings.campus_academic_scoped_enabled
    ):
        raise PermissionDeniedError("学院作息和组织业务尚未启用")


router = APIRouter(
    prefix="/colleges/{cid}/academic/semesters/{sid}/time-versions",
    tags=["college-time"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scheduling_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]


@router.get("")
def versions(cid: ResourceId, sid: ResourceId, actor: CurrentUserDep, db: Db, request: Request):
    return success(
        CollegeTimeService(db, actor, cid, sid).versions(),
        getattr(request.state, "request_id", None),
    )


@router.post("/preview")
def preview(
    cid: ResourceId,
    sid: ResourceId,
    body: TimeConfiguration,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    result = CollegeTimeService(db, actor, cid, sid).preview(body.model_dump())
    return success(result, getattr(request.state, "request_id", None))


@router.post("/publish")
def publish(
    cid: ResourceId,
    sid: ResourceId,
    body: TimePublish,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    result = CollegeTimeService(db, actor, cid, sid).publish(
        body.model_dump(exclude={"revision"}), body.revision
    )
    return success(result, getattr(request.state, "request_id", None))
