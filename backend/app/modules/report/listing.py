"""学院周报主记录发现；只把已发布版本视为最新可下载版本。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
from app.modules.identity.deps import CurrentUser, require_permission
from app.modules.identity.repository import IdentityRepository
from app.modules.report import permissions as perms
from app.modules.report.models import (
    Report,
    ReportSourceRevision,
    ReportVersion,
    ReportVersionStatus,
)

router = APIRouter(tags=["reports"])
ReportReadDep = Annotated[
    CurrentUser, Depends(require_permission(perms.REPORT_READ_PERMISSION))
]


def _time(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def summary_row(
    report: Report, version: ReportVersion | None, revision: int | None,
) -> dict[str, Any]:
    """响应仅陈列实际发布版本；生成中和失败版本不会冒充下载入口。"""
    if version is None or version.status != ReportVersionStatus.PUBLISHED.value:
        return {
            "report_id": str(report.id),
            "semester_id": str(report.semester_id),
            "week_no": report.week_no,
            "latest_version_id": None,
            "latest_version_no": None,
            "latest_version_created_at": None,
            "source_changed": False,
        }
    return {
        "report_id": str(report.id),
        "semester_id": str(report.semester_id),
        "week_no": report.week_no,
        "latest_version_id": str(version.id),
        "latest_version_no": version.version_no,
        "latest_version_created_at": _time(version.generated_at or version.created_at),
        "source_changed": version.source_revision < (revision or 0),
    }


class ReportListingService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_reports(
        self,
        actor: CurrentUser,
        *,
        semester_id: int | None,
        week_no: int | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        identity = IdentityRepository(self._session)
        if identity.get_user_by_id(actor.id) is None:
            raise UnauthenticatedError("操作者账号不可用")
        if perms.REPORT_READ_PERMISSION not in set(identity.list_effective_permissions(actor.id)):
            raise PermissionDeniedError()
        if not perms.is_manage_scope(perms.resolve_read_scope(actor.roles)):
            raise PermissionDeniedError("周报仅管理范围可见")

        conditions = [Report.scope == "COLLEGE"]
        if semester_id is not None:
            conditions.append(Report.semester_id == semester_id)
        if week_no is not None:
            conditions.append(Report.week_no == week_no)
        total = self._session.scalar(
            select(func.count()).select_from(Report).where(*conditions)
        ) or 0

        latest_published_no = (
            select(func.max(ReportVersion.version_no))
            .where(
                ReportVersion.report_id == Report.id,
                ReportVersion.status == ReportVersionStatus.PUBLISHED.value,
            )
            .correlate(Report)
            .scalar_subquery()
        )
        rows = self._session.execute(
            select(Report, ReportVersion, ReportSourceRevision.revision)
            .outerjoin(
                ReportVersion,
                and_(
                    ReportVersion.report_id == Report.id,
                    ReportVersion.version_no == latest_published_no,
                    ReportVersion.status == ReportVersionStatus.PUBLISHED.value,
                ),
            )
            .outerjoin(
                ReportSourceRevision,
                and_(
                    ReportSourceRevision.semester_id == Report.semester_id,
                    ReportSourceRevision.week_no == Report.week_no,
                ),
            )
            .where(*conditions)
            .order_by(Report.semester_id.desc(), Report.week_no.desc(), Report.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [summary_row(report, version, revision) for report, version, revision in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }


@router.get("/reports")
def list_reports(
    actor: ReportReadDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    week_no: Annotated[int | None, Query(ge=1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    data = ReportListingService(db).list_reports(
        actor, semester_id=semester_id, week_no=week_no, page=page, page_size=page_size
    )
    return success(data, getattr(request.state, "request_id", None))
