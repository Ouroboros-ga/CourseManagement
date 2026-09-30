"""审计只读 API，装配时挂 /api/v1。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.audit.service import AuditReadService
from app.modules.identity.deps import CurrentUser, require_permission

router = APIRouter(tags=["audit"])
AuditReadDep = Annotated[CurrentUser, Depends(require_permission(PermissionCode.AUDIT_READ.value))]


@router.get("/audit-logs")
def list_audit_logs(
    actor: AuditReadDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    date_from: Annotated[datetime, Query(description="UTC 起始时间")],
    date_to: Annotated[datetime, Query(description="UTC 结束时间")],
    actor_user_id: Annotated[int | None, Query(ge=1)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=64)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    data = AuditReadService(db).list_logs(
        actor.id, start=date_from, end=date_to, actor_user_id=actor_user_id,
        action=action, resource_type=resource_type, resource_id=resource_id,
        page=page, page_size=page_size,
    )
    return success(data, getattr(request.state, "request_id", None))


@router.get("/audit-logs/{log_id}")
def get_audit_log(
    log_id: int,
    actor: AuditReadDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> dict[str, object]:
    return success(
        AuditReadService(db).get(actor.id, log_id),
        getattr(request.state, "request_id", None),
    )
