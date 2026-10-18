"""教职工本人考勤更正与认定历史路由（T04、T07、审查 F6 交付缺口）。

`POST /me/teaching-attendance/{record_id}/corrections` 只在服务内锁事务完成授权
（账号→档案→考勤行→任务→授课关系）；`GET /me/attendance-records/{record_id}/versions?view=`
按工作视图判定读取范围，两种视图都能核对本人可见记录的历史。路由不做任何范围放行，
历史读取不加行锁。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.attendance.staff_service import StaffAttendanceSelfService
from app.modules.identity.staff_deps import CurrentStaffDep
from app.modules.inspection.staff_record_schemas import ViewLiteral

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
    service = StaffAttendanceSelfService(db)
    result = service.correct_teaching(staff.user, staff, record_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/me/attendance-records/{record_id}/versions")
def staff_list_attendance_versions(
    record_id: int,
    staff: CurrentStaffDep,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    view: ViewLiteral = Query(..., description="工作视图：teaching 或 responsible"),
) -> dict[str, object]:
    """本人可见考勤记录的认定历史。

    两种工作视图的明细都会给出 ``view_history`` 动作，因此历史也必须两种视图都可用：
    授课按有效授课关系判定，责任按该生在任务名单快照中的行政班是否由本人负责判定。
    范围逐请求复核，不使用全院 ``attendance.read``，也不给纯辅导员补全院读取权限。
    """
    service = StaffAttendanceSelfService(db)
    result = service.record_versions(staff.user, staff, record_id, view)
    return success([row.model_dump() for row in result], _rid(request))


__all__ = ["router"]
