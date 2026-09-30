"""审计只读查询，统一在数据库层应用筛选与分页。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


class AuditReadRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_logs(
        self,
        *,
        start: datetime,
        end: datetime,
        actor_user_id: int | None,
        action: str | None,
        resource_type: str | None,
        resource_id: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditLog], int]:
        conditions = [AuditLog.created_at >= start, AuditLog.created_at <= end]
        if actor_user_id is not None:
            conditions.append(AuditLog.actor_user_id == actor_user_id)
        if action is not None:
            conditions.append(AuditLog.action == action)
        if resource_type is not None:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            conditions.append(AuditLog.resource_id == resource_id)
        total = self._session.scalar(
            select(func.count()).select_from(AuditLog).where(*conditions)
        ) or 0
        rows = list(self._session.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars())
        return rows, total

    def get(self, log_id: int) -> AuditLog | None:
        return self._session.get(AuditLog, log_id)
