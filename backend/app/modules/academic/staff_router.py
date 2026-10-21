"""学院教职工档案、任职关系与绑定码的显式院级入口。

Router 只做参数解析与依赖装配；范围、版本、重叠与审计在 StaffManagementService 内
逐项复核。路径中的 cid 决定学校/学院归属，请求体不提供所有权字段。
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db, iso_utc
from app.modules.academic.scoped_router import require_scoped_academic_enabled
from app.modules.academic.staff_schemas import (
    AccountLink,
    AccountUnlink,
    BindingTokenReason,
    RelationEnd,
    ResponsibilityCreate,
    ResponsibilityHandover,
    StaffBindingExport,
    StaffCreate,
    StaffUpdate,
    TeachingAssignmentCreate,
)
from app.modules.academic.staff_service import StaffManagementService
from app.modules.identity.authorization import STAFF_MANAGE_ACTION
from app.modules.identity.deps import require_permission
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_binding import StaffBindingService
from app.modules.organization.router import require_campus_enabled

ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]

router = APIRouter(
    tags=["college-staff"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)],
)

ManageDep = Annotated[CurrentUser, Depends(require_permission(STAFF_MANAGE_ACTION))]


def get_service(
    cid: ResourceId,
    actor: ManageDep,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> StaffManagementService:
    return StaffManagementService(db, actor, cid, getattr(request.state, "request_id", None))


def get_binding_service(
    cid: ResourceId,
    db: Annotated[Session, Depends(get_db)],
) -> StaffBindingService:
    return StaffBindingService(db, college_id=cid)


ServiceDep = Annotated[StaffManagementService, Depends(get_service)]
BindingDep = Annotated[StaffBindingService, Depends(get_binding_service)]


@router.get("/colleges/{cid}/staff")
def list_staff(
    cid: ResourceId,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(pattern="^(ACTIVE|INACTIVE)$")] = None,
):
    return success(
        service.list_staff(params, keyword=keyword, status=status),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/staff")
def create_staff(cid: ResourceId, body: StaffCreate, service: ServiceDep, request: Request):
    return success(
        service.create_staff(body.model_dump()), getattr(request.state, "request_id", None)
    )


@router.post(
    "/colleges/{cid}/staff/export-binding-tokens",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
def export_binding_tokens(
    cid: ResourceId,
    body: StaffBindingExport,
    actor: ManageDep,
    service: BindingDep,
    request: Request,
):
    content = service.export_tokens_excel(
        actor=actor,
        staff_ids=[int(value) for value in body.staff_ids] if body.staff_ids is not None else None,
        keyword=body.keyword,
        days_valid=body.days_valid,
        request_id=getattr(request.state, "request_id", None),
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote('教职工绑定码.xlsx')}",
            "Cache-Control": "no-store",
        },
    )


@router.get("/colleges/{cid}/staff/{staff_id}")
def get_staff(cid: ResourceId, staff_id: ResourceId, service: ServiceDep, request: Request):
    return success(service.get_staff(staff_id), getattr(request.state, "request_id", None))


@router.patch("/colleges/{cid}/staff/{staff_id}")
def update_staff(
    cid: ResourceId, staff_id: ResourceId, body: StaffUpdate, service: ServiceDep, request: Request
):
    return success(
        service.update_staff(staff_id, body.model_dump(exclude_unset=True)),
        getattr(request.state, "request_id", None),
    )


@router.put("/colleges/{cid}/staff/{staff_id}/account")
def link_account(
    cid: ResourceId, staff_id: ResourceId, body: AccountLink, service: ServiceDep, request: Request
):
    return success(
        service.link_account(staff_id, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/staff/{staff_id}/account-unlink")
def unlink_account(
    cid: ResourceId,
    staff_id: ResourceId,
    body: AccountUnlink,
    service: ServiceDep,
    request: Request,
):
    return success(
        service.unlink_account(staff_id, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/staff/{staff_id}/binding-tokens")
def issue_binding_token(
    cid: ResourceId,
    staff_id: ResourceId,
    actor: ManageDep,
    service: BindingDep,
    request: Request,
    body: BindingTokenReason | None = None,
):
    token_id, code, expires_at = service.issue_token(
        actor=actor,
        staff_id=staff_id,
        reason=body.reason if body else None,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(
        {
            "token_id": str(token_id),
            "staff_id": str(staff_id),
            "plaintext_code": code,
            "expires_at": iso_utc(expires_at),
        },
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/staff-binding-tokens/{token_id}/revoke")
def revoke_binding_token(
    cid: ResourceId,
    token_id: ResourceId,
    actor: ManageDep,
    service: BindingDep,
    request: Request,
    body: BindingTokenReason | None = None,
):
    service.revoke_token(
        actor=actor,
        token_id=token_id,
        reason=body.reason if body else None,
        request_id=getattr(request.state, "request_id", None),
    )
    return success({"token_id": str(token_id)}, getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/teaching-staff-assignments")
def list_teaching_assignments(
    cid: ResourceId,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    paged: bool = False,
    staff_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    teaching_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
):
    if paged:
        return success(
            service.relation_page(
                "teaching", params, staff_id=staff_id, teaching_class_id=teaching_class_id
            ),
            getattr(request.state, "request_id", None),
        )
    return success(
        service.list_teaching_assignments(staff_id=staff_id, teaching_class_id=teaching_class_id),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/teaching-staff-assignments")
def create_teaching_assignment(
    cid: ResourceId, body: TeachingAssignmentCreate, service: ServiceDep, request: Request
):
    return success(
        service.create_teaching_assignment(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/teaching-staff-assignments/{rid}/end")
def end_teaching_assignment(
    cid: ResourceId, rid: ResourceId, body: RelationEnd, service: ServiceDep, request: Request
):
    return success(
        service.end_teaching_assignment(rid, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.get("/colleges/{cid}/class-staff-responsibilities")
def list_responsibilities(
    cid: ResourceId,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    paged: bool = False,
    staff_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    administrative_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
):
    if paged:
        return success(
            service.relation_page(
                "responsibility",
                params,
                staff_id=staff_id,
                administrative_class_id=administrative_class_id,
            ),
            getattr(request.state, "request_id", None),
        )
    return success(
        service.list_responsibilities(
            staff_id=staff_id, administrative_class_id=administrative_class_id
        ),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/class-staff-responsibilities")
def create_responsibility(
    cid: ResourceId, body: ResponsibilityCreate, service: ServiceDep, request: Request
):
    return success(
        service.create_responsibility(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/class-staff-responsibilities/{rid}/end")
def end_responsibility(
    cid: ResourceId, rid: ResourceId, body: RelationEnd, service: ServiceDep, request: Request
):
    return success(
        service.end_responsibility(rid, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/class-staff-responsibilities/{rid}/handover")
def handover_responsibility(
    cid: ResourceId,
    rid: ResourceId,
    body: ResponsibilityHandover,
    service: ServiceDep,
    request: Request,
):
    return success(
        service.handover_responsibility(rid, body.model_dump()),
        getattr(request.state, "request_id", None),
    )
