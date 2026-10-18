from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.responses import success
from app.modules.academic.time_router import Db, ResourceId
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled
from app.modules.volunteer.handover import (
    GroupHandoverService,
    Handover,
    HandoverConfirm,
    permission_sources,
)
from app.modules.volunteer.preparation import (
    GroupPreparationService,
    PreparationConfirm,
    SemesterPreparation,
)

router = APIRouter(
    prefix="/colleges/{cid}",
    tags=["organization-management"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)


@router.post("/volunteer-groups/{gid}/handover/preview")
def preview_handover(
    cid: ResourceId, gid: ResourceId, body: Handover, actor: CurrentUserDep, db: Db
):
    return success(GroupHandoverService(db, actor, cid, gid).preview(body.model_dump()))


@router.get("/volunteer-groups/{gid}/handover/candidates")
def handover_candidates(
    cid: ResourceId,
    gid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    keyword: Annotated[str, Query(max_length=128)] = "",
):
    return success(GroupHandoverService(db, actor, cid, gid).candidates(keyword))


@router.post("/volunteer-groups/{gid}/handover/confirm")
def confirm_handover(
    cid: ResourceId, gid: ResourceId, body: HandoverConfirm, actor: CurrentUserDep, db: Db
):
    return success(GroupHandoverService(db, actor, cid, gid).confirm(body.model_dump()))


@router.get("/permission-sources/me")
def my_sources(cid: ResourceId, actor: CurrentUserDep, db: Db):
    from app.modules.identity.resource_scope import resolve_scope

    resolve_scope(db, actor, cid, "volunteer.group.read")
    return success(permission_sources(db, actor.id, cid))


@router.post("/volunteer-groups/{gid}/semesters/{sid}/preparation/preview")
def preview_preparation(
    cid: ResourceId,
    gid: ResourceId,
    sid: ResourceId,
    body: SemesterPreparation,
    actor: CurrentUserDep,
    db: Db,
):
    return success(GroupPreparationService(db, actor, cid, gid, sid).preview(body.model_dump()))


@router.get("/volunteer-groups/{gid}/semesters/{sid}/preparation/source/{source_sid}")
def preparation_source(
    cid: ResourceId,
    gid: ResourceId,
    sid: ResourceId,
    source_sid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
):
    return success(GroupPreparationService(db, actor, cid, gid, sid).source(source_sid))


@router.post("/volunteer-groups/{gid}/semesters/{sid}/preparation/confirm")
def confirm_preparation(
    cid: ResourceId,
    gid: ResourceId,
    sid: ResourceId,
    body: PreparationConfirm,
    actor: CurrentUserDep,
    db: Db,
):
    return success(GroupPreparationService(db, actor, cid, gid, sid).confirm(body.model_dump()))
