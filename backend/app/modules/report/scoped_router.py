from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.identity.path_scope import validate_college_id
from app.modules.organization.router import require_campus_enabled
from app.modules.report.schemas import WeeklyVersionCreateRequest
from app.modules.report.version_service import ReportService

router = APIRouter(
    prefix="/colleges/{cid}",
    tags=["college-reports"],
    dependencies=[
        Depends(require_campus_enabled),
        Depends(require_business_scoped_enabled),
        Depends(validate_college_id),
    ],
)
Db = Annotated[Session, Depends(get_db)]
CollegeId = Annotated[int, Path(gt=0, le=2**63 - 1)]


@router.get("/reports")
def report_list(
    cid: CollegeId,
    actor: CurrentUserDep,
    db: Db,
    semester_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    week_no: Annotated[int | None, Query(ge=1, le=60)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    from app.modules.report.listing import ReportListingService

    return success(
        ReportListingService(db, college_id=cid).list_reports(
            actor, semester_id=semester_id, week_no=week_no, page=page, page_size=page_size
        )
    )


@router.post("/reports/weekly/versions")
def generate(
    cid: CollegeId,
    body: WeeklyVersionCreateRequest,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    result = ReportService(db, college_id=cid).generate_version(
        actor,
        semester_id=body.semester_id,
        week_no=body.week_no,
        scope=body.scope,
        reason=body.reason,
        request_id=getattr(request.state, "request_id", None),
    )
    return success(result.model_dump(mode="json"), getattr(request.state, "request_id", None))


@router.get("/reports/{rid}/versions")
def versions(cid: CollegeId, rid: CollegeId, actor: CurrentUserDep, db: Db, request: Request):
    result = ReportService(db, college_id=cid).list_versions(actor, rid)
    return success(result.model_dump(mode="json"), getattr(request.state, "request_id", None))


@router.get("/report-versions/{vid}/download")
def download(
    cid: CollegeId,
    vid: CollegeId,
    actor: CurrentUserDep,
    db: Db,
    kind: Literal["EXCEL", "SNAPSHOT", "WORD", "DETAIL_WORD", "STUDY_EXCEL"] = "EXCEL",
):
    from urllib.parse import quote

    content, content_type, filename = ReportService(db, college_id=cid).download(
        actor, vid, kind=kind
    )
    return Response(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


from app.modules.report.router import router as legacy_router

for route in legacy_router.routes:
    if isinstance(route, APIRoute) and route.path.startswith("/statistics/"):
        router.add_api_route(
            route.path,
            route.endpoint,
            methods=sorted(route.methods or set()),
            dependencies=route.dependencies,
            response_model=route.response_model,
            name=f"college_{route.name}",
            operation_id=f"college_{route.unique_id}",
        )
