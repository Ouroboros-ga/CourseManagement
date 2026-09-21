"""统一响应封装。

成功响应包含 data、requestId；分页包含 items、page、pageSize、total。
错误包含 code、message、fieldErrors、requestId（由异常处理器构造）。
ID 统一以字符串传输，避免 JavaScript 整数精度问题（技术方案 8.1）。
"""

from __future__ import annotations

from typing import Any


def to_id_str(value: int) -> str:
    """BIGINT 主键在 API 层以字符串对外暴露。"""
    return str(value)


def success(data: Any, request_id: str | None = None) -> dict[str, Any]:
    """标准成功响应体：{data, requestId}。"""
    return {"data": data, "requestId": request_id}
