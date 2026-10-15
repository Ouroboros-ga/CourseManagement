"""院级配置 HTTP 入口；授权和事务在 Service，不复用扁平权限并集。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.ownership import OwnershipService
from app.modules.organization.schemas import (
    CollegeCreate,
    CollegeUpdate,
    GrantCreate,
    GroupCreate,
    GroupPublish,
    GroupUpdate,
    OwnershipApply,
    OwnershipMapping,
    SchoolCreate,
    TypeCreate,
    TypeUpdate,
    Versioned,
)
from app.modules.organization.service import CampusService


def require_campus_enabled():
    if not get_settings().campus_configuration_enabled:
        raise AppError(
            ErrorCode.STATE_CONFLICT, "学院配置尚未启用，请先完成增量迁移并配置开关", 503
        )


router = APIRouter(tags=["campus-configuration"], dependencies=[Depends(require_campus_enabled)])
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def get_service(request: Request, db: Annotated[Session, Depends(get_db)]):
    return CampusService(db, getattr(request.state, "request_id", None))


ServiceDep = Annotated[CampusService, Depends(get_service)]


@router.get("/campus/ownership/unresolved/{kind}")
def unresolved_ownership(
    kind: str,
    actor: CurrentUserDep,
    service: ServiceDep,
    after_id: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    result = OwnershipService(service.db, service.request_id).unresolved(
        actor, kind, after_id=after_id, limit=limit
    )
    return success(result, service.request_id)


@router.post("/campus/ownership/preview")
def preview_ownership(body: OwnershipMapping, actor: CurrentUserDep, service: ServiceDep):
    result = OwnershipService(service.db, service.request_id).preview(actor, body.mappings)
    return success(result, service.request_id)


@router.post("/campus/ownership/apply")
def apply_ownership(body: OwnershipApply, actor: CurrentUserDep, service: ServiceDep):
    result = OwnershipService(service.db, service.request_id).apply(
        actor, body.mappings, body.revision
    )
    return success(result, service.request_id)


@router.get("/me/workspaces")
def workspaces(actor: CurrentUserDep, service: ServiceDep):
    return success(service.workspaces(actor), service.request_id)


@router.get("/colleges/{cid}/capabilities")
def capabilities(cid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.capabilities(actor, cid), service.request_id)


@router.get("/schools")
def schools(actor: CurrentUserDep, service: ServiceDep):
    return success(service.schools(actor), service.request_id)


@router.post("/schools")
def create_school(body: SchoolCreate, actor: CurrentUserDep, service: ServiceDep):
    return success(service.create_school(actor, body.model_dump()), service.request_id)


@router.post("/schools/{sid}/colleges")
def create_college(
    sid: ResourceId, body: CollegeCreate, actor: CurrentUserDep, service: ServiceDep
):
    return success(service.create_college(actor, sid, body.model_dump()), service.request_id)


@router.patch("/colleges/{cid}")
def update_college(
    cid: ResourceId, body: CollegeUpdate, actor: CurrentUserDep, service: ServiceDep
):
    return success(
        service.update_college(actor, cid, body.model_dump(exclude_unset=True)), service.request_id
    )


@router.get("/colleges/{cid}/grants")
def grants(cid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.list_grants(actor, cid), service.request_id)


@router.post("/colleges/{cid}/grants/preview")
def preview_grant(cid: ResourceId, body: GrantCreate, actor: CurrentUserDep, service: ServiceDep):
    return success(service.preview_grant(actor, cid, body.model_dump()), service.request_id)


@router.post("/colleges/{cid}/grants")
def create_grant(cid: ResourceId, body: GrantCreate, actor: CurrentUserDep, service: ServiceDep):
    return success(service.create_grant(actor, cid, body.model_dump()), service.request_id)


@router.post("/colleges/{cid}/grants/{rid}/revoke")
def revoke_grant(
    cid: ResourceId, rid: ResourceId, body: Versioned, actor: CurrentUserDep, service: ServiceDep
):
    return success(service.revoke_grant(actor, cid, rid, body.lock_version), service.request_id)


@router.get("/colleges/{cid}/course-types")
def types(cid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.list_types(actor, cid), service.request_id)


@router.post("/colleges/{cid}/course-types")
def create_type(cid: ResourceId, body: TypeCreate, actor: CurrentUserDep, service: ServiceDep):
    return success(service.create_type(actor, cid, body.model_dump()), service.request_id)


@router.patch("/colleges/{cid}/course-types/{rid}")
def update_type(
    cid: ResourceId, rid: ResourceId, body: TypeUpdate, actor: CurrentUserDep, service: ServiceDep
):
    return success(
        service.update_type(actor, cid, rid, body.model_dump(exclude_unset=True)),
        service.request_id,
    )


@router.get("/colleges/{cid}/course-types/{rid}/impact")
def type_impact(cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.configuration_impact(actor, cid, "course_type", rid), service.request_id)


@router.delete("/colleges/{cid}/course-types/{rid}")
def delete_type(
    cid: ResourceId, rid: ResourceId, body: Versioned, actor: CurrentUserDep, service: ServiceDep
):
    service.delete_type(actor, cid, rid, body.lock_version)
    return success(None, service.request_id)


@router.get("/colleges/{cid}/volunteer-groups")
def groups(cid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.list_groups(actor, cid), service.request_id)


@router.post("/colleges/{cid}/volunteer-groups")
def create_group(cid: ResourceId, body: GroupCreate, actor: CurrentUserDep, service: ServiceDep):
    return success(service.create_group(actor, cid, body.model_dump()), service.request_id)


@router.patch("/colleges/{cid}/groups/{rid}")
def update_group(
    cid: ResourceId, rid: ResourceId, body: GroupUpdate, actor: CurrentUserDep, service: ServiceDep
):
    return success(
        service.update_group(actor, cid, rid, body.model_dump(exclude_unset=True)),
        service.request_id,
    )


@router.get("/colleges/{cid}/groups/{rid}/impact")
def group_impact(cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.configuration_impact(actor, cid, "group", rid), service.request_id)


@router.delete("/colleges/{cid}/groups/{rid}")
def delete_group(
    cid: ResourceId, rid: ResourceId, body: Versioned, actor: CurrentUserDep, service: ServiceDep
):
    service.delete_group(actor, cid, rid, body.lock_version)
    return success(None, service.request_id)


@router.post("/colleges/{cid}/groups/{rid}/configuration/publish")
def publish_group(
    cid: ResourceId, rid: ResourceId, body: GroupPublish, actor: CurrentUserDep, service: ServiceDep
):
    return success(service.publish_group(actor, cid, rid, body.model_dump()), service.request_id)


@router.get("/colleges/{cid}/groups/{rid}/references")
def group_references(cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: ServiceDep):
    return success(service.group_references(actor, cid, rid), service.request_id)
