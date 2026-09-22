"""异议域路由（前缀在 main.py 挂 /api/v1）。

功能守卫用集中 PermissionCode，读取多路径用 require_any_permission，数据范围在 Service 施加：
- POST /attendance/{record_id}/objections：objection.create（SELF_STUDENT / OWN_OBJECTION）；
- GET /objections：管理路径（initial_review / final_review）或本人路径（objection.read）；
- GET /objections/{id}：同上（越界/不可见统一 404 防枚举）；
- POST /objections/{id}/initial-review：objection.initial_review（不改考勤）；
- POST /objections/{id}/final-review：objection.final_review（更正时另校验 correct）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.identity.deps import (
    CurrentUserDep,
    require_any_permission,
    require_permission,
)
from app.modules.objection.schemas import (
    ObjectionCreateRequest,
    ObjectionFinalReviewRequest,
    ObjectionInitialReviewRequest,
)
from app.modules.objection.service import ObjectionService

router = APIRouter(tags=["objection"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> ObjectionService:
    return ObjectionService(db)


ServiceDep = Annotated[ObjectionService, Depends(get_service)]

ObjectionCreateDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.OBJECTION_CREATE.value)),
]
# 异议读取：管理路径（初核/终审）或本人路径（objection.read）任一即可达。
ObjectionReadDep = Annotated[
    CurrentUserDep,
    Depends(
        require_any_permission(
            PermissionCode.OBJECTION_READ.value,
            PermissionCode.OBJECTION_INITIAL_REVIEW.value,
            PermissionCode.OBJECTION_FINAL_REVIEW.value,
        )
    ),
]
ObjectionInitialReviewDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.OBJECTION_INITIAL_REVIEW.value)),
]
ObjectionFinalReviewDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.OBJECTION_FINAL_REVIEW.value)),
]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ---- 创建：学生对本人某条考勤提异议 ----
@router.post("/attendance/{record_id}/objections")
def create_objection(
    record_id: int,
    body: ObjectionCreateRequest,
    actor: ObjectionCreateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create(actor, record_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 读取：管理范围或本人范围 ----
@router.get("/objections")
def list_objections(
    actor: ObjectionReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    attendance_record_id: Annotated[int | None, Query(ge=1)] = None,
    final_status: Annotated[str | None, Query(max_length=16)] = None,
    initial_status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    data = service.list_objections(
        actor,
        params,
        attendance_record_id=attendance_record_id,
        final_status=final_status,
        initial_status=initial_status,
    )
    return success(data, _rid(request))


@router.get("/objections/{objection_id}")
def get_objection(
    objection_id: int,
    actor: ObjectionReadDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.get_objection(actor, objection_id)
    return success(result.model_dump(), _rid(request))


# ---- 初核（不改考勤）----
@router.post("/objections/{objection_id}/initial-review")
def initial_review(
    objection_id: int,
    body: ObjectionInitialReviewRequest,
    actor: ObjectionInitialReviewDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.initial_review(actor, objection_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 终审（通过需更正时同事务改判考勤）----
@router.post("/objections/{objection_id}/final-review")
def final_review(
    objection_id: int,
    body: ObjectionFinalReviewRequest,
    actor: ObjectionFinalReviewDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.final_review(actor, objection_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))
