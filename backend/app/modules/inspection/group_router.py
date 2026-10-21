from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.time_router import require_scheduling_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.inspection.assignment_plan_schemas import (
    AssignmentPlanCommit,
    AssignmentPlanPreview,
)
from app.modules.inspection.assignment_plan_service import AssignmentPlanService
from app.modules.inspection.group_sampling import (
    GroupAssignRequest,
    GroupSampleConfirm,
    GroupSampleRequest,
    GroupSamplingService,
)
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}/groups/{gid}/inspection",
    tags=["group-inspection"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scheduling_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]


@router.post("/assignment-plans/preview")
def preview_assignment_plan(cid: ResourceId, gid: ResourceId, body: AssignmentPlanPreview,
                            actor: CurrentUserDep, db: Db, request: Request):
    """预览具体排班，不创建受派。

    返回 display（组/学期名称、授权任务资料、仅拟派发志愿者的姓名/学号/当前班级）。
    display 是展示投影，不参与确认；提交仍使用原 plan_id、revision 和精确警告确认。
    """
    return success(AssignmentPlanService(db, actor, cid, gid).preview(body.model_dump()),
                   getattr(request.state, "request_id", None))


@router.post("/assignment-plans/{plan_id}/commit")
def commit_assignment_plan(
    cid: ResourceId, gid: ResourceId, plan_id: str,
    body: AssignmentPlanCommit, actor: CurrentUserDep, db: Db, request: Request,
):
    return success(AssignmentPlanService(db, actor, cid, gid).commit(
        plan_id, body.model_dump(), getattr(request.state, "request_id", None)),
        getattr(request.state, "request_id", None))


@router.post("/assign")
def assign(
    cid: ResourceId,
    gid: ResourceId,
    body: GroupAssignRequest,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    result = GroupSamplingService(db, actor, cid, gid).assign(
        body.model_dump(), getattr(request.state, "request_id", None)
    )
    return success(result.model_dump(mode="json"), getattr(request.state, "request_id", None))


@router.post("/sample-preview")
def preview(
    cid: ResourceId,
    gid: ResourceId,
    body: GroupSampleRequest,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    return success(
        GroupSamplingService(db, actor, cid, gid).preview(body.model_dump()),
        getattr(request.state, "request_id", None),
    )


@router.post("/generate")
def generate(
    cid: ResourceId,
    gid: ResourceId,
    body: GroupSampleConfirm,
    actor: CurrentUserDep,
    db: Db,
    request: Request,
):
    result = GroupSamplingService(db, actor, cid, gid).generate(
        body.model_dump(exclude={"selection_revision"}),
        body.selection_revision,
        getattr(request.state, "request_id", None),
    )
    return success(result.model_dump(mode="json"), getattr(request.state, "request_id", None))
