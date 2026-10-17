"""教职工本人授课考勤更正路由（T04）。

仅新增 `POST /me/teaching-attendance/{record_id}/corrections`；授权完全在服务内
锁事务完成（账号→档案→考勤行→任务→授课关系），路由不做任何范围放行。
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


__all__ = ["router"]
