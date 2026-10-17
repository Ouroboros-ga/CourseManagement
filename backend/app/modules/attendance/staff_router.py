"""教职工本人授课考勤更正与认定历史路由（T04、T07 交付缺口）。

`POST /me/teaching-attendance/{record_id}/corrections` 与
`GET /me/teaching-attendance/{record_id}/versions` 都只在服务内锁事务完成授权
（账号→档案→考勤行→任务→授课关系），路由不做任何范围放行；历史读取不加行锁。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.attendance.staff_service import StaffTeachingAttendanceService
from app.modules.identity.staff_deps import CurrentStaffDep

router = APIRouter(tags=["attendance"])


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/me/teaching-attendance/{record_id}/corrections")
def staff_correct_teaching_attendance(
    record_id: int,
    body: AttendanceCorrectionRequest,
    request: Request,
    staff: CurrentStaffDep,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    service = StaffTeachingAttendanceService(db)
    result = service.correct_teaching(staff.user, staff, record_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/me/teaching-attendance/{record_id}/versions")
def staff_list_teaching_attendance_versions(
    record_id: int,
    staff: CurrentStaffDep,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """本人授课记录的认定历史；范围逐请求按有效授课关系复核，不使用全院读取权限。"""
    service = StaffTeachingAttendanceService(db)
    result = service.teaching_versions(staff.user, staff, record_id)
    return success([row.model_dump() for row in result], _rid(request))


__all__ = ["router"]
