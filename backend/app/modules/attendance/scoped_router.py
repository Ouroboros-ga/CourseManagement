"""管理范围明确写入 URL；本人接口继续沿用绑定范围。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.attendance.browse import FiltersDep
from app.modules.attendance.schemas import (
    AttendanceCorrectionRequest,
    AttendanceGroupEnvelope,
    ManagementAttendanceDetailEnvelope,
    ManagementAttendanceListEnvelope,
)
from app.modules.attendance.scoped_service import ScopedAttendanceService
from app.modules.identity.deps import CurrentUserDep
from app.modules.inspection.dimensions import DimensionsDep
from app.modules.organization.router import require_campus_enabled


def require_business_scoped_enabled():
    if not get_settings().campus_business_scoped_enabled:
        raise AppError(ErrorCode.STATE_CONFLICT, "院级正式业务链尚未启用", 503)


router = APIRouter(
    tags=["college-attendance"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def get_service(cid: ResourceId, actor: CurrentUserDep, db: Annotated[Session, Depends(get_db)]):
    return ScopedAttendanceService(db, actor, cid)


Service = Annotated[ScopedAttendanceService, Depends(get_service)]


@router.get("/colleges/{cid}/attendance", response_model=ManagementAttendanceListEnvelope)
def list_attendance(
    cid: ResourceId,
    actor: CurrentUserDep,
    service: Service,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    dimensions: DimensionsDep,
    filters: FiltersDep,
    task_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    semester_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    effective_type: Annotated[str | None, Query(max_length=16)] = None,
):
    return success(
        service.list_attendance(
            actor,
            params,
            task_id=task_id,
            semester_id=semester_id,
            dimensions=dimensions,
            effective_type=effective_type,
            filters=filters,
        ),
        getattr(request.state, "request_id", None),
    )


@router.get("/colleges/{cid}/attendance/groups", response_model=AttendanceGroupEnvelope)
def grouped_attendance(
    cid: ResourceId, actor: CurrentUserDep, service: Service, request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    filters: FiltersDep, dimensions: DimensionsDep,
    group_by: Annotated[str, Query(pattern="^(task|administrative_class)$")] = "task",
    semester_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    effective_type: Annotated[str | None, Query(pattern="^(NORMAL|LATE|ABSENT|LEAVE)$")] = None,
):
    """在 attendance.read 的任务归属范围内统计，历史班级未知时明确单列。"""
    return success(service.list_groups(actor, params, group_by=group_by,
        semester_id=semester_id, effective_type=effective_type,
        filters=filters, dimensions=dimensions), getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/attendance/{rid}", response_model=ManagementAttendanceDetailEnvelope)
def get_attendance(
    cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: Service, request: Request
):
    return success(
        service.get_attendance(actor, rid).model_dump(), getattr(request.state, "request_id", None)
    )


@router.get("/colleges/{cid}/attendance/{rid}/versions")
def versions(
    cid: ResourceId, rid: ResourceId, actor: CurrentUserDep, service: Service, request: Request
):
    return success(
        [row.model_dump() for row in service.list_versions(actor, rid)],
        getattr(request.state, "request_id", None),
    )


@router.post(
    "/colleges/{cid}/attendance/{rid}/corrections",
    response_model=ManagementAttendanceDetailEnvelope,
)
def correct(
    cid: ResourceId,
    rid: ResourceId,
    body: AttendanceCorrectionRequest,
    actor: CurrentUserDep,
    service: Service,
    request: Request,
):
    request_id = getattr(request.state, "request_id", None)
    return success(service.correct(actor, rid, body, request_id).model_dump(), request_id)


@router.post(
    "/colleges/{cid}/attendance/{rid}/archived-corrections",
    response_model=ManagementAttendanceDetailEnvelope,
)
def correct_archived(
    cid: ResourceId,
    rid: ResourceId,
    body: AttendanceCorrectionRequest,
    actor: CurrentUserDep,
    service: Service,
    request: Request,
):
    request_id = getattr(request.state, "request_id", None)
    return success(service.correct_archived(actor, rid, body, request_id).model_dump(), request_id)
