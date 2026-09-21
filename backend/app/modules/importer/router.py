"""导入路由：multipart 上传→预览、确认、错误、模板（技术方案 19，PERMISSIONS.md 12.5）。

前缀在 main.py 挂载为 /api/v1。功能守卫：导入相关端点要求 `import.execute`
（路由级早拦），目标资源 manage 与组合权限在 Service 事务内纵深复核；模板下载
仅需目标 manage（Service 内动态判定，路由仅要求已登录）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.identity.deps import CurrentUserDep, require_permission
from app.modules.importer.service import ImporterService

router = APIRouter(tags=["import"])

ImportExecuteDep = Annotated[
    CurrentUserDep, Depends(require_permission(PermissionCode.IMPORT_EXECUTE.value))
]


def get_service(db: Annotated[Session, Depends(get_db)]) -> ImporterService:
    return ImporterService(db)


ServiceDep = Annotated[ImporterService, Depends(get_service)]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ---- 模板（仅需目标 manage，路由仅要求登录，具体在 Service 判定）----
@router.get("/import-templates/{target}")
def get_import_template(
    target: str, actor: CurrentUserDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.get_template(actor, target)
    return success(result.model_dump(), _rid(request))


# ---- 创建预览（上传 xlsx，解析暂存，不写业务表）----
@router.post("/imports")
async def create_import(
    request: Request,
    actor: ImportExecuteDep,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    target: Annotated[str, Form()],
    semester_id: Annotated[int | None, Form()] = None,
    teaching_class_id: Annotated[int | None, Form()] = None,
    replace: Annotated[bool, Form()] = True,
) -> dict[str, object]:
    content = await file.read()
    result = service.create_preview(
        actor,
        target=target,
        content=content,
        semester_id=semester_id,
        teaching_class_id=teaching_class_id,
        filename=file.filename,
        replace=replace,
        request_id=_rid(request),
    )
    return success(result.model_dump(), _rid(request))


@router.get("/imports/{batch_id}")
def get_import(
    batch_id: int, actor: ImportExecuteDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.get_batch(actor, batch_id)
    return success(result.model_dump(), _rid(request))


@router.post("/imports/{batch_id}/confirm")
def confirm_import(
    batch_id: int, actor: ImportExecuteDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.confirm(actor, batch_id, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/imports/{batch_id}/errors")
def import_errors(
    batch_id: int,
    actor: ImportExecuteDep,
    service: ServiceDep,
    request: Request,
    _q: Annotated[str | None, Query()] = None,  # 预留过滤参数位
) -> dict[str, object]:
    result = service.get_errors(actor, batch_id)
    return success(result, _rid(request))
