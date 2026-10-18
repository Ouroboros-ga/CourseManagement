"""轻量识别与模板入口；不建立新草稿表，不包含正式写入。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.importer.catalog import build_template_pack, catalog_items
from app.modules.importer.intake import inspect_upload
from app.modules.importer.scoped_service import ScopedImporterService
from app.modules.importer.zip_preview import MAX_FILE
from app.modules.organization.router import require_campus_enabled

router = APIRouter(
    prefix="/colleges/{cid}/imports/intake",
    tags=["import-intake"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)
CollegeId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def available(service):
    rows = []
    for row in catalog_items():
        try:
            service.get_template(service.actor, row["target"])
            rows.append(row)
        except (PermissionDeniedError, NotFoundError):
            continue
    return rows


@router.get("/catalog")
def catalog(
    cid: CollegeId, actor: CurrentUserDep, db: Annotated[Session, Depends(get_db)], request: Request
):
    service = ScopedImporterService(db, actor, cid)
    with service.operation("import.execute"):
        return success(
            {"types": available(service), "max_files": 20, "max_file_bytes": MAX_FILE},
            getattr(request.state, "request_id", None),
        )


@router.post("/inspect")
async def inspect(
    cid: CollegeId,
    actor: CurrentUserDep,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    file: Annotated[UploadFile, File()],
):
    service = ScopedImporterService(db, actor, cid)
    # I/O 与解析不持有业务行锁。授权读取不代表任何类型可被正式导入。
    with service.operation("import.execute"):
        pass
    db.rollback()
    content = await file.read(MAX_FILE + 1)
    from starlette.concurrency import run_in_threadpool

    rows = await run_in_threadpool(inspect_upload, content, file.filename or "未命名表格")
    return success(
        {"files": rows, "business_data_applied": False}, getattr(request.state, "request_id", None)
    )


@router.get("/templates")
def templates(cid: CollegeId, actor: CurrentUserDep, db: Annotated[Session, Depends(get_db)]):
    service = ScopedImporterService(db, actor, cid)
    with service.operation("import.execute"):
        targets = [row["target"] for row in available(service)]
    db.rollback()
    return Response(
        build_template_pack(targets),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="college-import-templates.zip"',
        },
    )
