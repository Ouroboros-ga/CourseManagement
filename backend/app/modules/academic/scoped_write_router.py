from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.scoped_router import require_scoped_academic_enabled
from app.modules.academic.scoped_write_schemas import (
    CreateBody,
    DeleteMany,
    ElectiveBatch,
    QualificationUpsert,
    SemesterReset,
    UpdateBody,
)
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}/academic",
    tags=["college-academic-writes"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)],
)
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Kind = Literal["students", "courses", "teaching-classes", "schedules", "administrative-classes"]
Db = Annotated[Session, Depends(get_db)]


@router.post("/teaching-classes/batch-elective")
def batch_elective(
    cid: ResourceId, actor: CurrentUserDep, db: Db, request: Request, body: ElectiveBatch
):
    return success(
        ScopedAcademicWriteService(
            db, actor, cid, getattr(request.state, "request_id", None)
        ).batch_elective(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/semesters/{sid}/reset-data")
def reset_semester(
    cid: ResourceId,
    sid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
    body: SemesterReset,
):
    return success(
        ScopedAcademicWriteService(
            db, actor, cid, getattr(request.state, "request_id", None)
        ).reset_semester(sid, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.get("/semesters/{sid}/reset-preview")
def reset_preview(
    cid: ResourceId, sid: ResourceId, actor: CurrentUserDep, db: Db, request: Request
):
    return success(
        ScopedAcademicWriteService(
            db, actor, cid, getattr(request.state, "request_id", None)
        ).reset_preview(sid),
        getattr(request.state, "request_id", None),
    )


@router.put("/qualifications")
def upsert_qualification(
    cid: ResourceId, body: QualificationUpsert, actor: CurrentUserDep, db: Db, request: Request
):
    return success(
        ScopedAcademicWriteService(
            db, actor, cid, getattr(request.state, "request_id", None)
        ).upsert_qualification(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/{kind}")
def create(
    cid: ResourceId,
    kind: Kind,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
    body: Annotated[CreateBody, Body()],
):
    result = ScopedAcademicWriteService(
        db, actor, cid, getattr(request.state, "request_id", None)
    ).create(kind.replace("-", "_"), body.model_dump())
    return success(result, getattr(request.state, "request_id", None))


@router.patch("/{kind}/{rid}")
def update(
    cid: ResourceId,
    kind: Kind,
    rid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
    body: Annotated[UpdateBody, Body()],
):
    result = ScopedAcademicWriteService(
        db, actor, cid, getattr(request.state, "request_id", None)
    ).update(kind.replace("-", "_"), rid, body.model_dump(exclude_unset=True))
    return success(result, getattr(request.state, "request_id", None))


@router.post("/{kind}/batch-delete")
def delete_many(
    cid: ResourceId, kind: Kind, body: DeleteMany, actor: CurrentUserDep, db: Db, request: Request
):
    result = ScopedAcademicWriteService(
        db, actor, cid, getattr(request.state, "request_id", None)
    ).delete_many(
        kind.replace("-", "_"),
        body.ids,
        {int(key): value for key, value in body.versions.items()},
        body.reason,
    )
    return success(result, getattr(request.state, "request_id", None))


@router.delete("/{kind}/{rid}")
def delete_one(
    cid: ResourceId,
    kind: Kind,
    rid: ResourceId,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
    version: Annotated[int, Query(ge=0)],
    reason: Annotated[str | None, Query(max_length=512)] = None,
):
    service = ScopedAcademicWriteService(db, actor, cid, getattr(request.state, "request_id", None))
    result = service.delete_many(kind.replace("-", "_"), [rid], {rid: version}, reason)
    return success(result, getattr(request.state, "request_id", None))
