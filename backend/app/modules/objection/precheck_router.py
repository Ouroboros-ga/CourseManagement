"""College management API; assistant tools never receive these capabilities."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.objection.precheck_management import PrecheckManagementService
from app.modules.organization.router import require_campus_enabled
from app.modules.organization.schemas import StrictModel


def require_precheck_enabled():
    if not get_settings().agent_objection_precheck_enabled:
        raise NotFoundError()


router = APIRouter(
    tags=["college-objection-precheck"],
    dependencies=[
        Depends(require_campus_enabled),
        Depends(require_business_scoped_enabled),
        Depends(require_precheck_enabled),
    ],
)
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Db = Annotated[Session, Depends(get_db)]


class PrecheckPolicyUpdate(StrictModel):
    enabled: StrictBool
    current_version: int = Field(ge=0, le=2**31 - 1, strict=True)


class PrecheckRetryRequest(StrictModel):
    expected_job_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("expected_job_id")
    @classmethod
    def bounded_id(cls, value):
        if value is not None and int(value) >= 2**63:
            raise ValueError("预审标识超出范围")
        return value


@router.get("/colleges/{cid}/objection-precheck-policy")
def get_policy(cid: ResourceId, actor: CurrentUserDep, db: Db, request: Request):
    return success(
        PrecheckManagementService(db, cid).policy(actor), getattr(request.state, "request_id", None)
    )


@router.put("/colleges/{cid}/objection-precheck-policy")
def update_policy(
    cid: ResourceId, body: PrecheckPolicyUpdate, actor: CurrentUserDep, db: Db, request: Request
):
    return success(
        PrecheckManagementService(db, cid).update_policy(
            actor,
            enabled=body.enabled,
            current_version=body.current_version,
        ),
        getattr(request.state, "request_id", None),
    )


@router.get("/colleges/{cid}/objections/{rid}/precheck")
def get_latest(cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, db: Db, request: Request):
    return success(
        PrecheckManagementService(db, cid).latest(actor, rid),
        getattr(request.state, "request_id", None),
    )


@router.post("/colleges/{cid}/objections/{rid}/precheck/retry")
def retry(
    cid: ResourceId,
    rid: ResourceId,
    body: PrecheckRetryRequest,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    request_id = getattr(request.state, "request_id", None)
    return success(
        PrecheckManagementService(db, cid).retry(
            actor,
            rid,
            expected_job_id=int(body.expected_job_id) if body.expected_job_id else None,
            request_id=request_id,
        ),
        request_id,
    )
