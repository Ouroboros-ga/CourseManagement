"""教务明确发布和绑定学生初始化来源；全部默认关闭，迁移验收后启用。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.academic.publication_schemas import (
    NoticeEnvelope,
    PreviewEnvelope,
    PublishEnvelope,
    PublishRequest,
)
from app.modules.academic.publication_service import (
    AcademicPublicationService,
    MyAcademicSourceService,
)
from app.modules.academic.scoped_router import require_scoped_academic_enabled
from app.modules.identity.deps import BindingCompleteDep, CurrentUserDep
from app.modules.organization.router import require_campus_enabled


def require_publication_enabled():
    if not get_settings().academic_publication_enabled:
        raise AppError(ErrorCode.STATE_CONFLICT, "教务发布及初始化来源尚未启用", 503)


router = APIRouter(
    tags=["academic-publication"], dependencies=[Depends(require_publication_enabled)]
)
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
Db = Annotated[Session, Depends(get_db)]


@router.post(
    "/colleges/{cid}/academic/semesters/{sid}/publication-preview",
    response_model=PreviewEnvelope,
    dependencies=[Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)],
)
def preview(cid: ResourceId, sid: ResourceId, actor: CurrentUserDep, db: Db, request: Request):
    return success(
        AcademicPublicationService(db, actor, cid).preview(sid),
        getattr(request.state, "request_id", None),
    )


@router.post(
    "/colleges/{cid}/academic/semesters/{sid}/publish",
    response_model=PublishEnvelope,
    dependencies=[Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)],
)
def publish(
    cid: ResourceId,
    sid: ResourceId,
    body: PublishRequest,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    request_id = getattr(request.state, "request_id", None)
    return success(
        AcademicPublicationService(db, actor, cid, request_id).publish(sid, body.source_revision),
        request_id,
    )


@router.get("/me/academic-notices", response_model=NoticeEnvelope)
def notices(
    actor: BindingCompleteDep,
    db: Db,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
):
    return success(
        MyAcademicSourceService(db, actor.id).notices(params),
        getattr(request.state, "request_id", None),
    )
