"""审计读取服务：权限纵深校验、窗口限制和输出脱敏。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ErrorCode, NotFoundError, PermissionDeniedError
from app.core.permissions import PermissionCode
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditReadRepository
from app.modules.audit.schemas import safe_snapshot, validate_window
from app.modules.identity.repository import IdentityRepository


def _db_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _dto(log: AuditLog, *, detail: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": str(log.id),
        "actor_user_id": str(log.actor_user_id) if log.actor_user_id is not None else None,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "created_at": _db_time(log.created_at).isoformat() + "Z",
    }
    if detail:
        item.update(
            before=safe_snapshot(log.before_json),
            after=safe_snapshot(log.after_json),
            request_id=log.request_id,
        )
    return item


class AuditReadService:
    def __init__(self, session: Session, *, college_id: int | None = None) -> None:
        self._session = session
        self._college_id = college_id
        self._repo = AuditReadRepository(session, college_id=college_id)

    def _require_permission(self, actor_id: int) -> None:
        identity = IdentityRepository(self._session)
        if self._college_id is not None:
            from app.modules.identity.resource_scope import resolve_scope
            from app.modules.identity.service import CurrentUser
            resolve_scope(self._session, CurrentUser(actor_id, None, "", "ACTIVE", [], []),
                          self._college_id, "audit.read")
            return
        from app.core.config import get_settings
        if (get_settings().campus_business_scoped_enabled
                and "SUPER_ADMIN" not in identity.list_role_codes(actor_id)):
            raise PermissionDeniedError("请使用明确学院的审计入口；未知历史仅超管可见")
        if identity.get_user_by_id(actor_id) is None or (
            PermissionCode.AUDIT_READ.value
            not in set(identity.list_effective_permissions(actor_id))
        ):
            raise PermissionDeniedError()

    def list_logs(
        self,
        actor_id: int,
        *,
        start: datetime,
        end: datetime,
        actor_user_id: int | None,
        action: str | None,
        resource_type: str | None,
        resource_id: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        self._require_permission(actor_id)
        try:
            validate_window(start, end)
        except ValueError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc), http_status=422) from exc
        rows, total = self._repo.list_logs(
            start=_db_time(start), end=_db_time(end), actor_user_id=actor_user_id,
            action=action, resource_type=resource_type, resource_id=resource_id,
            page=page, page_size=page_size,
        )
        return {
            "items": [_dto(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def get(self, actor_id: int, log_id: int) -> dict[str, Any]:
        self._require_permission(actor_id)
        row = self._repo.get(log_id)
        if row is None:
            raise NotFoundError("审计记录不存在")
        return _dto(row, detail=True)
