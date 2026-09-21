"""跨业务通用分页查询参数与工具。

分页限制最大 pageSize，避免深分页拖垮数据库；必要时按需求使用游标分页。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> PageParams:
    """FastAPI 依赖：解析并校验分页参数。"""
    return PageParams(page=page, page_size=page_size)
