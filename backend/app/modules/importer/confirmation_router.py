from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile
from pydantic import Field
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.importer.confirmation_set import ImportConfirmationSet
from app.modules.importer.scoped_service import ScopedImporterService
from app.modules.organization.router import require_campus_enabled
from app.modules.organization.schemas import StrictModel

Id = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class ConfirmationSelection(StrictModel):
    batch_ids: list[Id] = Field(min_length=1, max_length=20)


class ConfirmationRequest(ConfirmationSelection):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class PersonLinkSelection(StrictModel):
    kind: Literal["teaching", "responsibility"]
    semester_id: Id | None = None


class PersonLinkConfirmation(PersonLinkSelection):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


router = APIRouter(
    prefix="/colleges/{cid}/imports/confirmation-set",
    tags=["import-confirmation"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)


@router.post("/person-links/preview")
def person_link_preview(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    body: PersonLinkSelection,
    request: Request,
):
    from app.modules.importer.person_reconciliation import PersonLinkReconciliation

    result = PersonLinkReconciliation(ScopedImporterService(db, actor, cid)).preview(
        body.kind, int(body.semester_id) if body.semester_id else None)
    return success(result, getattr(request.state, "request_id", None))


@router.post("/person-links/confirm")
def person_link_confirm(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    body: PersonLinkConfirmation,
    request: Request,
):
    from app.modules.importer.person_reconciliation import PersonLinkReconciliation

    result = PersonLinkReconciliation(ScopedImporterService(db, actor, cid)).confirm(
        body.kind, int(body.semester_id) if body.semester_id else None,
        body.revision, getattr(request.state, "request_id", None))
    return success(result, getattr(request.state, "request_id", None))


@router.post("/zip-preview")
async def zip_preview(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    file: Annotated[UploadFile, File()],
    target: Annotated[str, Form()],
    semester_id: Annotated[int | None, Form()] = None,
    teaching_class_id: Annotated[int | None, Form()] = None,
    course_type_id: Annotated[int | None, Form()] = None,
):
    from app.modules.importer.zip_preview import MAX_FILE, preview_zip

    result = preview_zip(
        ScopedImporterService(db, actor, cid),
        actor,
        await file.read(MAX_FILE + 1),
        target=target,
        semester_id=semester_id,
        teaching_class_id=teaching_class_id,
        course_type_id=course_type_id,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(result, getattr(request.state, "request_id", None))


@router.post("/preview")
def preview(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    body: ConfirmationSelection,
    request: Request,
):
    result = ImportConfirmationSet(ScopedImporterService(db, actor, cid)).preview(
        [int(value) for value in body.batch_ids]
    )
    return success(result, getattr(request.state, "request_id", None))


@router.post("/confirm")
def confirm(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    body: ConfirmationRequest,
    request: Request,
):
    rid = getattr(request.state, "request_id", None)
    result = ImportConfirmationSet(ScopedImporterService(db, actor, cid)).confirm(
        [int(value) for value in body.batch_ids], body.revision, rid
    )
    return success(result, rid)
