from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.overview import WorkspaceOverviewService
from app.modules.organization.router import require_campus_enabled

router = APIRouter(tags=["workspace-overview"], dependencies=[Depends(require_campus_enabled)])


@router.get("/colleges/{cid}/overview")
def overview(
    cid: Annotated[int, Path(gt=0, le=2**63 - 1)],
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    semester_id: Annotated[int, Query(gt=0, le=2**63 - 1)],
):
    return success(
        WorkspaceOverviewService(db, actor, cid).read(semester_id),
        getattr(request.state, "request_id", None),
    )
