from fastapi import APIRouter, Depends

from app.common.responses import success
from app.modules.academic.school_time import (
    SchoolTimeService,
    TemplateAdopt,
    TemplateAdoption,
    TemplatePublish,
)
from app.modules.academic.time_router import Db, ResourceId, require_scheduling_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    tags=["school-time"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scheduling_enabled)],
)


@router.get("/school/academic/semesters/{sid}/time-templates")
def school_templates(sid: ResourceId, actor: CurrentUserDep, db: Db):
    return success(SchoolTimeService(db, actor, sid).list())


@router.post("/school/academic/semesters/{sid}/time-templates")
def publish_template(sid: ResourceId, body: TemplatePublish, actor: CurrentUserDep, db: Db):
    return success(SchoolTimeService(db, actor, sid).publish(body.model_dump()))


@router.get("/colleges/{cid}/academic/semesters/{sid}/school-time-templates")
def available_templates(cid: ResourceId, sid: ResourceId, actor: CurrentUserDep, db: Db):
    return success(SchoolTimeService(db, actor, sid).list(cid))


@router.post("/colleges/{cid}/academic/semesters/{sid}/school-time-templates/preview")
def adoption_preview(
    cid: ResourceId, sid: ResourceId, body: TemplateAdoption, actor: CurrentUserDep, db: Db
):
    return success(SchoolTimeService(db, actor, sid).preview_adoption(cid, body.model_dump()))


@router.post("/colleges/{cid}/academic/semesters/{sid}/school-time-templates/adopt")
def adopt_template(
    cid: ResourceId, sid: ResourceId, body: TemplateAdopt, actor: CurrentUserDep, db: Db
):
    return success(SchoolTimeService(db, actor, sid).adopt(cid, body.model_dump()))
