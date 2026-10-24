"""Login-bound original uploads; no model-selected path, actor or source scope."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode, NotFoundError
from app.modules.agent.conversation_router import ConversationCreate
from app.modules.agent.import_workspace import ImportWorkspaceService
from app.modules.identity.deps import CurrentUserDep, SessionIdDep
from app.modules.importer.limits import MAX_ARCHIVE_BYTES


def require_enabled(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    settings = get_settings()
    if not settings.agent_tools_enabled or not settings.agent_import_workspace_enabled:
        raise NotFoundError()


router = APIRouter(
    prefix="/assistant/management/imports",
    tags=["agent-import-workspaces"],
    dependencies=[Depends(require_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
WorkspaceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
ScopeId = Annotated[int, Query(gt=0, le=2**63 - 1)]
FormId = Annotated[str, Form(pattern=r"^[1-9][0-9]{0,18}$")]


def service_for(db):
    settings = get_settings()
    if settings.agent_management_chat_config is None:
        raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE, "资料助手暂未配置", 503)
    return ImportWorkspaceService(
        db,
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=settings.agent_management_chat_config.tool_app_key_id,
    )


@router.post("")
async def upload(
    actor: CurrentUserDep,
    sid: SessionIdDep,
    db: Db,
    request: Request,
    college_id: FormId,
    semester_id: FormId,
    request_key: Annotated[str, Form(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
    file: Annotated[UploadFile, File()],
):
    try:
        form = await request.form()
        fields = {"college_id", "semester_id", "request_key", "file"}
        if set(form) != fields or any(len(form.getlist(name)) != 1 for name in fields):
            raise AppError(ErrorCode.VALIDATION_ERROR, "资料上传字段不符合要求", 422)
        try:
            scope = ConversationCreate(college_id=college_id, semester_id=semester_id)
        except ValidationError:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学院或学期编号不合法", 422) from None
        service = service_for(db)
        # Recheck before reading bytes; the service rechecks after storage I/O as well.
        service._preflight(actor.id, sid, int(scope.college_id), int(scope.semester_id))
        db.rollback()
        content = await file.read(MAX_ARCHIVE_BYTES + 1)
        result = await run_in_threadpool(
            service.upload,
            user_id=actor.id,
            session_id=sid,
            college_id=int(scope.college_id),
            semester_id=int(scope.semester_id),
            content=content,
            filename=file.filename or "未命名资料",
            request_key=request_key,
            request_id=getattr(request.state, "request_id", None),
        )
        return success(result, getattr(request.state, "request_id", None))
    finally:
        await file.close()


@router.get("/{workspace_id}")
def read(
    workspace_id: WorkspaceId,
    college_id: ScopeId,
    semester_id: ScopeId,
    actor: CurrentUserDep,
    sid: SessionIdDep,
    db: Db,
    request: Request,
):
    return success(
        service_for(db).read(
            workspace_id,
            user_id=actor.id,
            session_id=sid,
            college_id=college_id,
            semester_id=semester_id,
        ),
        getattr(request.state, "request_id", None),
    )


@router.post("/{workspace_id}/cancel")
def cancel(
    workspace_id: WorkspaceId,
    body: ConversationCreate,
    actor: CurrentUserDep,
    sid: SessionIdDep,
    db: Db,
    request: Request,
):
    service = service_for(db)
    scope = dict(
        user_id=actor.id,
        session_id=sid,
        college_id=int(body.college_id),
        semester_id=int(body.semester_id),
    )
    service.cancel(workspace_id, **scope)
    return success(service.read(workspace_id, **scope), getattr(request.state, "request_id", None))
