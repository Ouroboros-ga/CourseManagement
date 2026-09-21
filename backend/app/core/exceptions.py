"""统一异常与错误码。

错误响应包含 code、message、fieldErrors、requestId；不返回堆栈或数据库内部信息。
典型业务错误码见技术方案第 20 节。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """稳定业务错误码字符串。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    CSRF_FAILED = "CSRF_FAILED"
    NOT_FOUND = "NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    ASSIGNMENT_CONFLICT = "ASSIGNMENT_CONFLICT"
    DUPLICATE_ACTIVE_OBJECTION = "DUPLICATE_ACTIVE_OBJECTION"
    FILE_EXPIRED = "FILE_EXPIRED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """应用层基类异常，映射到统一错误响应。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int = 400,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.field_errors = field_errors or {}


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(ErrorCode.NOT_FOUND, message, http_status=404)


class PermissionDeniedError(AppError):
    def __init__(self, message: str = "无权访问该资源") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message, http_status=403)


class CsrfError(AppError):
    def __init__(self, message: str = "跨站请求校验未通过") -> None:
        super().__init__(ErrorCode.CSRF_FAILED, message, http_status=403)


class UnauthenticatedError(AppError):
    def __init__(self, message: str = "未登录或会话已失效") -> None:
        super().__init__(ErrorCode.UNAUTHENTICATED, message, http_status=401)


class ConflictError(AppError):
    def __init__(
        self,
        code: ErrorCode = ErrorCode.STATE_CONFLICT,
        message: str = "资源状态冲突，请刷新后重试",
    ) -> None:
        super().__init__(code, message, http_status=409)
