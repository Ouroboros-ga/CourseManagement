"""Explicit management actions, separate from trusted background workflow tools."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.identity.deps import CurrentUserDep
from app.modules.inspection.weekly_management import WeeklyManagementService
from app.modules.inspection.weekly_schemas import WeeklyPlanUpdate
from app.modules.inspection.weekly_service import WeeklyInspectionService
from app.modules.organization.schemas import StrictModel


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/colleges/{cid}/groups/{gid}/inspection/weekly", tags=["weekly-inspection"],
    dependencies=[Depends(private_response)],
)
Db = Annotated[Session, Depends(get_db)]
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
SemesterId = Annotated[int, Query(gt=0, le=2**63 - 1)]


class VersionAction(StrictModel):
    current_version: int = Field(strict=True, ge=1)


class RecheckAction(StrictModel):
    expected_assignment_plan_id: str | None = Field(max_length=36, strict=True)

    @field_validator("expected_assignment_plan_id")
    @classmethod
    def valid_id(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("草案标识无效")
        return value


def reply(request, value):
    return success(value, getattr(request.state, "request_id", None))


@router.get("/policy")
def policy(cid: ResourceId, gid: ResourceId, semester_id: SemesterId,
           actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyManagementService(db, cid, gid, semester_id).policy(actor))


@router.put("/policy")
def save(cid: ResourceId, gid: ResourceId, semester_id: SemesterId,
         body: WeeklyPlanUpdate, actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyInspectionService(db, cid, gid, semester_id).save(
        actor, body.model_dump(),
    ))


@router.post("/policy/pause")
def pause(cid: ResourceId, gid: ResourceId, semester_id: SemesterId,
          body: VersionAction, actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyInspectionService(db, cid, gid, semester_id).pause(
        actor, body.current_version,
    ))


@router.post("/due")
def register(cid: ResourceId, gid: ResourceId, semester_id: SemesterId,
             body: VersionAction, actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyManagementService(db, cid, gid, semester_id).register_due(
        actor, body.current_version,
    ))


@router.get("/executions")
def history(cid: ResourceId, gid: ResourceId, semester_id: SemesterId,
            actor: CurrentUserDep, db: Db, request: Request,
            limit: Annotated[int, Query(ge=1, le=50)] = 20,
            before_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None):
    return reply(request, WeeklyManagementService(db, cid, gid, semester_id).history(
        actor, limit=limit, before_id=before_id,
    ))


@router.get("/executions/{eid}")
def detail(cid: ResourceId, gid: ResourceId, eid: ResourceId, semester_id: SemesterId,
           actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyManagementService(db, cid, gid, semester_id).detail(actor, eid))


@router.post("/executions/{eid}/recheck")
def recheck(cid: ResourceId, gid: ResourceId, eid: ResourceId, semester_id: SemesterId,
            body: RecheckAction, actor: CurrentUserDep, db: Db, request: Request):
    return reply(request, WeeklyManagementService(db, cid, gid, semester_id).recheck(
        actor, eid, body.expected_assignment_plan_id,
    ))
