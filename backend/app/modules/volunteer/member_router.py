from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled
from app.modules.volunteer.member_batch import (
    GroupMemberBatchService,
    MemberBatch,
    MemberBatchCommit,
)
from app.modules.volunteer.member_schemas import MemberCreate, MemberRevoke, MemberUpdate
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.unavailability_service import (
    UnavailabilityCreate,
    UnavailabilityDecision,
    UnavailabilityService,
    UnavailabilityWithdrawal,
)

router = APIRouter(
    prefix="/colleges/{cid}/groups/{gid}",
    tags=["group-members"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
SemesterId = Annotated[int, Query(gt=0, le=2**63 - 1)]


@router.get("/member-candidates")
def member_candidates(
    cid: ResourceId,
    gid: ResourceId,
    semester_id: SemesterId,
    effective_from: date,
    effective_to: date,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
    keyword: Annotated[str, Query(max_length=100)] = "",
    school: bool = False,
):
    return success(
        GroupMemberService(db, actor, cid, gid).candidates(
            semester_id, effective_from, effective_to, keyword, school=school
        ),
        getattr(request.state, "request_id", None),
    )


@router.get("/members")
def members(
    cid: ResourceId,
    gid: ResourceId,
    semester_id: SemesterId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).members(semester_id),
        getattr(request.state, "request_id", None),
    )


@router.post("/members")
def create(
    cid: ResourceId,
    gid: ResourceId,
    body: MemberCreate,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).create(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/members/{mid}/revoke")
def revoke(
    cid: ResourceId,
    gid: ResourceId,
    mid: ResourceId,
    body: MemberRevoke,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).revoke(
            mid, body.lock_version, confirm_future_assignments=body.confirm_future_assignments
        ),
        getattr(request.state, "request_id", None),
    )


@router.post("/support-authorizations")
def support(
    cid: ResourceId,
    gid: ResourceId,
    body: MemberCreate,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).authorize_support(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.get("/support-authorizations")
def list_supports(
    cid: ResourceId,
    gid: ResourceId,
    semester_id: SemesterId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).supports(semester_id),
        getattr(request.state, "request_id", None),
    )


@router.get("/members/{mid}/impact")
def member_impact(
    cid: ResourceId,
    gid: ResourceId,
    mid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).impact(mid),
        getattr(request.state, "request_id", None),
    )


@router.get("/support-authorizations/{rid}/impact")
def support_impact(
    cid: ResourceId,
    gid: ResourceId,
    rid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).impact(rid, support=True),
        getattr(request.state, "request_id", None),
    )


@router.patch("/members/{mid}")
def update_member(
    cid: ResourceId,
    gid: ResourceId,
    mid: ResourceId,
    body: MemberUpdate,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).update(mid, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.patch("/support-authorizations/{rid}")
def update_support(
    cid: ResourceId,
    gid: ResourceId,
    rid: ResourceId,
    body: MemberUpdate,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).update(rid, body.model_dump(), support=True),
        getattr(request.state, "request_id", None),
    )


@router.post("/support-authorizations/{rid}/revoke")
def revoke_support(
    cid: ResourceId,
    gid: ResourceId,
    rid: ResourceId,
    body: MemberRevoke,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupMemberService(db, actor, cid, gid).revoke(
            rid,
            body.lock_version,
            support=True,
            confirm_future_assignments=body.confirm_future_assignments,
        ),
        getattr(request.state, "request_id", None),
    )


@router.post("/members/batch/preview")
def member_batch_preview(cid: ResourceId, gid: ResourceId, body: MemberBatch, actor: CurrentUserDep, db: Db, request: Request):
    return success(GroupMemberBatchService(db, actor, cid, gid).preview(body.model_dump()), getattr(request.state, "request_id", None))


@router.post("/members/batch/commit")
def member_batch_commit(cid: ResourceId, gid: ResourceId, body: MemberBatchCommit, actor: CurrentUserDep, db: Db, request: Request):
    return success(GroupMemberBatchService(db, actor, cid, gid).commit(body.model_dump(exclude={"revision"}), body.revision), getattr(request.state, "request_id", None))


@router.get("/unavailability")
def unavailability_list(cid: ResourceId, gid: ResourceId, semester_id: SemesterId, actor: CurrentUserDep, db: Db, request: Request, page: Annotated[int, Query(ge=1)] = 1):
    return success(UnavailabilityService(db, actor, cid, gid).list(semester_id, page=page), getattr(request.state, "request_id", None))


@router.post("/unavailability")
def unavailability_create(cid: ResourceId, gid: ResourceId, body: UnavailabilityCreate, actor: CurrentUserDep, db: Db, request: Request):
    return success(UnavailabilityService(db, actor, cid, gid).create(body.model_dump()), getattr(request.state, "request_id", None))


@router.get("/unavailability/{rid}/impact")
def unavailability_impact(cid: ResourceId, gid: ResourceId, rid: ResourceId, actor: CurrentUserDep, db: Db, request: Request):
    return success(UnavailabilityService(db, actor, cid, gid).impact(rid), getattr(request.state, "request_id", None))


@router.post("/unavailability/{rid}/decision")
def unavailability_decide(cid: ResourceId, gid: ResourceId, rid: ResourceId, body: UnavailabilityDecision, actor: CurrentUserDep, db: Db, request: Request):
    return success(UnavailabilityService(db, actor, cid, gid).decide(rid, body.model_dump()), getattr(request.state, "request_id", None))


@router.get("/me/unavailability")
def own_unavailability_list(cid: ResourceId, gid: ResourceId, semester_id: SemesterId, actor: CurrentUserDep, db: Db, request: Request, page: Annotated[int, Query(ge=1)] = 1):
    return success(UnavailabilityService(db, actor, cid, gid).list(semester_id, page=page, own=True), getattr(request.state, "request_id", None))


@router.post("/me/unavailability")
def own_unavailability_create(cid: ResourceId, gid: ResourceId, body: UnavailabilityCreate, actor: CurrentUserDep, db: Db, request: Request):
    return success(UnavailabilityService(db, actor, cid, gid).create(body.model_dump(), own=True), getattr(request.state, "request_id", None))


@router.post("/me/unavailability/{rid}/withdraw")
def own_unavailability_withdraw(cid: ResourceId, gid: ResourceId, rid: ResourceId, body: UnavailabilityWithdrawal, actor: CurrentUserDep, db: Db, request: Request):
    return success(UnavailabilityService(db, actor, cid, gid).decide(rid, body.model_dump(), own=True), getattr(request.state, "request_id", None))
