from fastapi import APIRouter, Depends

from app.common.responses import success
from app.modules.academic.archive import ArchiveConfirm, ArchiveRequest, SemesterArchiveService
from app.modules.academic.time_router import Db, ResourceId
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled
from app.modules.report.campus_dimensions import CampusDimensionsService

router = APIRouter(
    tags=["campus-management"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)


@router.post("/school/academic/semesters/{sid}/archive/preview")
def archive_preview(sid: ResourceId, body: ArchiveRequest, actor: CurrentUserDep, db: Db):
    return success(SemesterArchiveService(db, actor, sid).preview(body.model_dump()))


@router.post("/school/academic/semesters/{sid}/archive/confirm")
def archive_confirm(sid: ResourceId, body: ArchiveConfirm, actor: CurrentUserDep, db: Db):
    return success(SemesterArchiveService(db, actor, sid).confirm(body.model_dump()))


@router.get("/colleges/{cid}/statistics/semesters/{sid}/campus-dimensions")
def college_dimensions(cid: ResourceId, sid: ResourceId, actor: CurrentUserDep, db: Db):
    return success(CampusDimensionsService(db, actor, sid, cid).summary())


@router.get("/school/statistics/semesters/{sid}/campus-dimensions")
def school_dimensions(sid: ResourceId, actor: CurrentUserDep, db: Db):
    return success(CampusDimensionsService(db, actor, sid).summary())
