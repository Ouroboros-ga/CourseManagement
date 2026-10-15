from fastapi import APIRouter, Depends

from app.common.responses import success
from app.modules.academic.offerings import OfferingLink, OfferingLinkConfirm, OfferingService
from app.modules.academic.time_router import Db, ResourceId, require_scheduling_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}/academic/teaching-classes/{tid}/shared-identity",
    tags=["shared-academic-identity"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scheduling_enabled)],
)


@router.get("/candidates")
def candidates(cid: ResourceId, tid: ResourceId, actor: CurrentUserDep, db: Db):
    return success(OfferingService(db, actor, cid, tid).candidates())


@router.post("/preview")
def preview(cid: ResourceId, tid: ResourceId, body: OfferingLink, actor: CurrentUserDep, db: Db):
    return success(OfferingService(db, actor, cid, tid).preview(body.model_dump()))


@router.post("/confirm")
def confirm(
    cid: ResourceId, tid: ResourceId, body: OfferingLinkConfirm, actor: CurrentUserDep, db: Db
):
    return success(OfferingService(db, actor, cid, tid).confirm(body.model_dump()))
