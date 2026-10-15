from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.school_time_schemas import (
    TemplateContent,
    TemplateImport,
    TemplateRevision,
    TemplateStatus,
)
from app.modules.academic.school_time_service import SchoolTimeTemplateService
from app.modules.academic.time_router import ResourceId, require_scheduling_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled

router = APIRouter(tags=["school-time-templates"], dependencies=[Depends(require_campus_enabled)])


def get_service(db: Annotated[Session, Depends(get_db)], actor: CurrentUserDep, request: Request):
    return SchoolTimeTemplateService(db, actor, getattr(request.state, "request_id", None))


Service = Annotated[SchoolTimeTemplateService, Depends(get_service)]


def result(data, service):
    return success(data, service.campus.request_id)


@router.get("/schools/{sid}/time-templates")
def templates(sid: ResourceId, service: Service):
    return result(service.catalog(sid), service)


@router.post("/schools/{sid}/time-templates")
def create(sid: ResourceId, body: TemplateContent, service: Service):
    return result(service.create(sid, body.model_dump()), service)


@router.get("/schools/{sid}/time-templates/{tid}/versions")
def versions(sid: ResourceId, tid: ResourceId, service: Service):
    return result(service.versions(sid, tid), service)


@router.patch("/schools/{sid}/time-templates/{tid}")
def revise(sid: ResourceId, tid: ResourceId, body: TemplateRevision, service: Service):
    return result(service.revise(sid, tid, body.model_dump()), service)


@router.post("/schools/{sid}/time-templates/{tid}/status")
def status(sid: ResourceId, tid: ResourceId, body: TemplateStatus, service: Service):
    return result(service.set_status(sid, tid, body.model_dump()), service)


@router.get("/colleges/{cid}/time-templates")
def college_catalog(cid: ResourceId, service: Service):
    return result(service.college_catalog(cid), service)


@router.post(
    "/colleges/{cid}/academic/semesters/{sid}/time-versions/profiles/from-template",
    dependencies=[Depends(require_scheduling_enabled)],
)
def import_draft(cid: ResourceId, sid: ResourceId, body: TemplateImport, service: Service):
    return result(service.import_draft(cid, sid, body.model_dump()), service)


@router.get("/colleges/{cid}/academic/semesters/{sid}/time-template-updates")
def updates(cid: ResourceId, sid: ResourceId, service: Service):
    return result(service.updates(cid, sid), service)
