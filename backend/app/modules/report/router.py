"""统计域路由（前缀在 main.py 挂 /api/v1，技术方案 §19 端点映射）。

功能守卫用集中 PermissionCode（statistics.read），数据范围与口径在 Service 施加。
本波仅只读统计端点；周报生成/版本/下载端点归 W7c（report.read / report.generate）。

- GET /statistics/attendance：学期 + 周次/日期窗，聚合当前有效考勤（先范围后聚合）；
- GET /statistics/incomplete-tasks：分页未完成清单，同时输出当前状态与截止时快照两指标。
"""

from __future__ import annotations

from datetime import date as date_
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.identity.deps import CurrentUserDep, require_permission
from app.modules.report.permissions import STATISTICS_READ_PERMISSION
from app.modules.report.schemas import AttendanceStatsQuery
from app.modules.report.service import StatisticsService

router = APIRouter(tags=["statistics"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> StatisticsService:
    return StatisticsService(db)


ServiceDep = Annotated[StatisticsService, Depends(get_service)]

StatisticsReadDep = Annotated[
    CurrentUserDep, Depends(require_permission(STATISTICS_READ_PERMISSION))
]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _build_window_query(
    semester_id: int,
    week_no: int | None,
    date_from: date_ | None,
    date_to: date_ | None,
) -> AttendanceStatsQuery:
    """装配时间窗查询；把「周次与日期窗互斥且必居其一」的校验失败转成统一 422。

    AttendanceStatsQuery 的 model_validator 抛 pydantic ValidationError，若直接冒泡会变成
    500（非 FastAPI 请求校验路径），此处捕获并转投 AppError(VALIDATION_ERROR, 422)。
    """
    try:
        return AttendanceStatsQuery(
            semester_id=semester_id,
            week_no=week_no,
            date_from=date_from,
            date_to=date_to,
        )
    except ValidationError as exc:
        msg = (
            "; ".join(str(e.get("msg", "时间窗参数不合法")) for e in exc.errors())
            or "时间窗参数不合法"
        )
        raise AppError(ErrorCode.VALIDATION_ERROR, msg, http_status=422) from exc


# ---- 考勤统计 ----
@router.get("/statistics/attendance")
def attendance_statistics(
    actor: StatisticsReadDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
    week_no: Annotated[int | None, Query(ge=1)] = None,
    date_from: Annotated[date_ | None, Query()] = None,
    date_to: Annotated[date_ | None, Query()] = None,
    include_tasks: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    query = _build_window_query(semester_id, week_no, date_from, date_to)
    result = service.attendance_stats(actor, query, include_tasks=include_tasks)
    return success(result.model_dump(), _rid(request))


# ---- 未完成清单（当前状态派生 + 截止时快照，两指标不混名）----
@router.get("/statistics/incomplete-tasks")
def incomplete_tasks(
    actor: StatisticsReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int, Query(ge=1)],
    week_no: Annotated[int | None, Query(ge=1)] = None,
    date_from: Annotated[date_ | None, Query()] = None,
    date_to: Annotated[date_ | None, Query()] = None,
    only_current_incomplete: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    query = _build_window_query(semester_id, week_no, date_from, date_to)
    result = service.incomplete_tasks(
        actor,
        semester_id=query.semester_id,
        week_no=query.week_no,
        date_from=query.date_from,
        date_to=query.date_to,
        params=params,
        only_current_incomplete=only_current_incomplete,
    )
    return success(result.model_dump(), _rid(request))
