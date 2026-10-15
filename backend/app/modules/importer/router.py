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


def get_service(request: Request, actor: CurrentUserDep,
                db: Annotated[Session, Depends(get_db)]) -> ImporterService:
    from app.core.config import get_settings
    from app.core.exceptions import AppError, ErrorCode
    from app.modules.importer.scoped_service import ScopedImporterService

    cid = request.path_params.get("cid")
    if cid is not None:
        if not cid.isascii() or not cid.isdecimal() or not 0 < int(cid) < 2**63:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学院 ID 不合法", 422)
        return ScopedImporterService(db, actor, int(cid))
    if get_settings().campus_business_scoped_enabled:
        raise AppError(ErrorCode.STATE_CONFLICT, "请从已授权学院工作区执行导入", 409)
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
    from app.core.exceptions import AppError, ErrorCode
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise AppError(ErrorCode.VALIDATION_ERROR, "单个导入文件不能超过 10 MiB", 422)
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


@router.post("/imports/bulk")
async def bulk_import(
    request: Request,
    actor: ImportExecuteDep,
    service: ServiceDep,
    semester_id: Annotated[int, Form()],
    files: Annotated[list[UploadFile], File()],
) -> dict[str, object]:
    """旧兼容入口逐文件预览并确认；前面的成功文件不会随后续文件失败回滚。"""
    raw_files: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        raw_files.append((f.filename or "file", data))
    result = service.import_bulk_files(
        actor,
        semester_id=semester_id,
        files=raw_files,
        request_id=_rid(request),
    )
    return success(result, _rid(request))
