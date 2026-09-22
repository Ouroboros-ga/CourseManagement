"""文件路由：受限上传、短时访问链接与签名下载（技术方案 16，前缀在 main.py 挂 /api/v1）。

- POST /files：登录且已完成绑定的用户上传材料（multipart），经校验与存储后建 READY 行；
- GET /files/{id}/access：按业务资源归属鉴权后返回短时签名链接（技术方案 16.2）；
- GET /files/{id}/download：签名链接落地下载，不再鉴权、只验 HMAC 与有效期（技术方案
  16.2 明确不即时撤销已发出链接；密钥不外泄）。日志不记录完整签名 URL。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.file.schemas import FileAccessResponse
from app.modules.file.service import FileService
from app.modules.identity.deps import BindingCompleteDep, CurrentUserDep

router = APIRouter(tags=["file"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> FileService:
    return FileService(db)


ServiceDep = Annotated[FileService, Depends(get_service)]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/files")
async def upload_file(
    request: Request,
    actor: BindingCompleteDep,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    category: Annotated[str, Form()],
) -> dict[str, object]:
    content = await file.read()
    result = service.upload(
        actor,
        category=category,
        content=content,
        filename=file.filename,
        declared_content_type=file.content_type,
        request_id=_rid(request),
    )
    return success(result.model_dump(), _rid(request))


@router.get("/files/{file_id}/access")
def get_file_access(
    file_id: int,
    actor: CurrentUserDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result: FileAccessResponse = service.get_access(actor, file_id)
    return success(result.model_dump(), _rid(request))


@router.get("/files/{file_id}/download")
def download_file(
    file_id: int,
    service: ServiceDep,
    expires: Annotated[int, Query(ge=0)],
    sig: Annotated[str, Query(min_length=1)],
) -> Response:
    data, content_type, filename = service.download(file_id, expires, sig)
    headers = {}
    if filename:
        # 文件名仅展示用，对象键为服务端随机，绝不以原文件名作路径。
        safe = filename.replace('"', "")
        headers["Content-Disposition"] = f'inline; filename="{safe}"'
    return Response(content=data, media_type=content_type, headers=headers)


__all__ = ["router"]
