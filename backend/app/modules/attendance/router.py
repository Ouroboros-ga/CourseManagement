"""考勤域路由（前缀在 main.py 挂 /api/v1）。

功能守卫沿用集中 PermissionCode，数据范围在 Service 内施加（PERMISSIONS.md 12.8）：
- GET /attendance：attendance.read + 管理范围（越权读全量 403）；
- GET /me/attendance：attendance.read + SELF_STUDENT（强制本人 student_id）；
- GET /attendance/{id} 与 /attendance/{id}/versions：attendance.read + 范围（防枚举 404）；
- POST /attendance/{id}/corrections：attendance.correct（仅超管/教师）+ current_version 乐观锁。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.attendance.browse import FiltersDep
from app.modules.attendance.schemas import (
    AttendanceCorrectionRequest,
    AttendanceDetailEnvelope,
    AttendanceGroupEnvelope,
    AttendanceListEnvelope,
    ManagementAttendanceListEnvelope,
)
from app.modules.attendance.service import AttendanceService
from app.modules.identity.deps import CurrentUserDep, require_permission
from app.modules.inspection.dimensions import DimensionsDep

router = APIRouter(tags=["attendance"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AttendanceService:
    return AttendanceService(db)


ServiceDep = Annotated[AttendanceService, Depends(get_service)]

AttendanceReadDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ATTENDANCE_READ.value)),
]
AttendanceCorrectDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ATTENDANCE_CORRECT.value)),
]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ---- 本人考勤（SELF_STUDENT；须在 /{record_id} 之前声明，避免 me 被当 id 吞掉）----
@router.get("/me/attendance", response_model=AttendanceListEnvelope)
def list_my_attendance(
    actor: AttendanceReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    task_id: Annotated[int | None, Query(ge=1)] = None,
    effective_type: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    data = service.list_my_attendance(actor, params, task_id=task_id, effective_type=effective_type)
    return success(data, _rid(request))


# ---- 管理范围考勤列表 ----
@router.get("/attendance", response_model=ManagementAttendanceListEnvelope)
def list_attendance(
    actor: AttendanceReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    dimensions: DimensionsDep,
    filters: FiltersDep,
    task_id: Annotated[int | None, Query(ge=1)] = None,
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    effective_type: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    data = service.list_attendance(
        actor,
        params,
        task_id=task_id,
        semester_id=semester_id,
        dimensions=dimensions,
        effective_type=effective_type,
        filters=filters,
    )
    return success(data, _rid(request))


@router.get("/attendance/groups", response_model=AttendanceGroupEnvelope)
def list_attendance_groups(
    actor: AttendanceReadDep, service: ServiceDep, request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    filters: FiltersDep, dimensions: DimensionsDep,
    group_by: Annotated[str, Query(pattern="^(task|administrative_class)$")] = "task",
    semester_id: Annotated[int | None, Query(gt=0)] = None,
    effective_type: Annotated[str | None, Query(pattern="^(NORMAL|LATE|ABSENT|LEAVE)$")] = None,
):
    """完整管理范围按具体查课任务或历史行政班汇总，分页单位为组。"""
    return success(service.list_groups(actor, params, group_by=group_by,
        semester_id=semester_id, effective_type=effective_type,
        filters=filters, dimensions=dimensions), _rid(request))


# ---- 单条考勤详情（按范围鉴权）----
@router.get("/attendance/{record_id}", response_model=AttendanceDetailEnvelope)
def get_attendance(
    record_id: int,
    actor: AttendanceReadDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object] | JSONResponse:
    result = service.get_attendance(actor, record_id)
    payload = success(result.model_dump(), _rid(request))
    # The shared legacy detail URL also serves Web while college mode is off.
    # Preserve its management metadata without exposing it in student responses.
    if service._can_manage(actor):
        return JSONResponse(content=jsonable_encoder(payload))
    return payload


# ---- 考勤历史版本（按范围鉴权）----
@router.get("/attendance/{record_id}/versions")
def list_attendance_versions(
    record_id: int,
    actor: AttendanceReadDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.list_versions(actor, record_id)
    return success([v.model_dump() for v in result], _rid(request))


# ---- 更正最终考勤（attendance.correct）----
@router.post("/attendance/{record_id}/corrections")
def correct_attendance(
    record_id: int,
    body: AttendanceCorrectionRequest,
    actor: AttendanceCorrectDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.correct(actor, record_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))
