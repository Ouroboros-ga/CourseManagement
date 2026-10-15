"""云端本人课表读取/增删改；没有管理者代改或正式业务写入口。"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.academic.publication_router import require_publication_enabled
from app.modules.academic.publication_schemas import InitializeRequest
from app.modules.identity.deps import BindingCompleteDep
from app.modules.timetable.schemas import (
    EntryCreate,
    EntryDelete,
    EntryUpdate,
    OccurrenceEdit,
    PersonalSemestersEnvelope,
    TimetableEnvelope,
)
from app.modules.timetable.service import PersonalTimetableService

router = APIRouter(tags=["personal-timetable"], dependencies=[Depends(require_publication_enabled)])
Db = Annotated[Session, Depends(get_db)]
SemesterId = Annotated[int, Query(gt=0, le=2**63 - 1)]


@router.post("/me/timetable/initialize", response_model=TimetableEnvelope)
def initialize(body: InitializeRequest, actor: BindingCompleteDep, db: Db, request: Request):
    if int(body.semester_id) >= 2**63:
        raise AppError(ErrorCode.VALIDATION_ERROR, "学期标识超出范围", 422)
    return success(
        PersonalTimetableService(db, actor.id).initialize(int(body.semester_id)),
        getattr(request.state, "request_id", None),
    )


@router.get("/me/timetable/semesters", response_model=PersonalSemestersEnvelope)
def semesters(actor: BindingCompleteDep, db: Db, request: Request):
    return success(
        PersonalTimetableService(db, actor.id).semesters(),
        getattr(request.state, "request_id", None),
    )


@router.get("/me/timetable", response_model=TimetableEnvelope)
def get_timetable(semester_id: SemesterId, actor: BindingCompleteDep, db: Db, request: Request):
    return success(
        PersonalTimetableService(db, actor.id).get(semester_id),
        getattr(request.state, "request_id", None),
    )


@router.get("/me/timetable/deleted-entries")
def deleted_entries(semester_id: SemesterId, actor: BindingCompleteDep, db: Db):
    return success(PersonalTimetableService(db, actor.id).deleted(semester_id))


@router.post("/me/timetable/entries/{eid}/restore", response_model=TimetableEnvelope)
def restore_entry(eid: UUID, semester_id: SemesterId, body: EntryDelete,
                  actor: BindingCompleteDep, db: Db):
    return success(PersonalTimetableService(db, actor.id).restore(
        semester_id, str(eid), body.current_version))


@router.put("/me/timetable/entries/{eid}/exceptions/{day}", response_model=TimetableEnvelope)
def put_exception(eid: UUID, day: date, semester_id: SemesterId, body: OccurrenceEdit,
                  actor: BindingCompleteDep, db: Db):
    return success(PersonalTimetableService(db, actor.id).set_exception(
        semester_id, str(eid), day, body.model_dump(exclude_unset=True)))


@router.delete("/me/timetable/entries/{eid}/exceptions/{day}", response_model=TimetableEnvelope)
def delete_exception(eid: UUID, day: date, semester_id: SemesterId, body: EntryDelete,
                     actor: BindingCompleteDep, db: Db):
    return success(PersonalTimetableService(db, actor.id).remove_exception(
        semester_id, str(eid), day, body.current_version))


@router.post("/me/timetable/entries", response_model=TimetableEnvelope)
def create_entry(
    body: EntryCreate, semester_id: SemesterId, actor: BindingCompleteDep, db: Db, request: Request
):
    return success(
        PersonalTimetableService(db, actor.id).create_entry(semester_id, body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.patch("/me/timetable/entries/{eid}", response_model=TimetableEnvelope)
def update_entry(
    eid: Annotated[UUID, Path()],
    body: EntryUpdate,
    semester_id: SemesterId,
    actor: BindingCompleteDep,
    db: Db,
    request: Request,
):
    return success(
        PersonalTimetableService(db, actor.id).update_entry(
            semester_id, str(eid), body.model_dump(exclude_unset=True)
        ),
        getattr(request.state, "request_id", None),
    )


@router.delete("/me/timetable/entries/{eid}", response_model=TimetableEnvelope)
def delete_entry(
    eid: Annotated[UUID, Path()],
    body: EntryDelete,
    semester_id: SemesterId,
    actor: BindingCompleteDep,
    db: Db,
    request: Request,
):
    return success(
        PersonalTimetableService(db, actor.id).delete_entry(
            semester_id, str(eid), body.current_version
        ),
        getattr(request.state, "request_id", None),
    )
