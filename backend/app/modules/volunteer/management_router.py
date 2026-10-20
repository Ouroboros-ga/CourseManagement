from datetime import date
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


@router.get("/volunteer-groups/semester-overview")
def group_semester_overview(
    cid: ResourceId,
    semester_id: Annotated[int, Query(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Db,
    as_of: date | None = None,
):
    from app.modules.identity.role_scope import business_today
    from app.modules.volunteer.overview import semester_overview

    return success(semester_overview(db, actor, cid, semester_id, as_of or business_today()))


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
    include_teaching_classes: bool = True,
):
    return success(
        GroupPreparationService(db, actor, cid, gid, sid).source(
            source_sid, include_teaching_classes=include_teaching_classes
        )
    )


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
