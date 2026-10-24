"""Authenticated management conversations; credentials remain server-side."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode, NotFoundError
from app.modules.agent.adp_chat import AdpChatClient
from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.conversation_service import ConversationService
from app.modules.agent.schemas import Id, TimetableQuery
from app.modules.identity.deps import CurrentUserDep, SessionIdDep


class ConversationCreate(TimetableQuery):
    college_id: Id


class ConversationMessage(ConversationCreate):
    text: str = Field(min_length=1, max_length=4000)
    request_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def require_enabled(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    if not get_settings().agent_tools_enabled:
        raise NotFoundError()


router = APIRouter(
    prefix="/assistant/management/conversations",
    tags=["agent-conversations"],
    dependencies=[Depends(require_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
ConversationId = Annotated[int, Path(gt=0, le=2**63 - 1)]
ScopeId = Annotated[int, Query(gt=0, le=2**63 - 1)]
BeforeId = Annotated[int | None, Query(gt=0, le=2**63 - 1)]


def service_for(db):
    settings = get_settings()
    config = settings.agent_management_chat_config
    if config is None:
        raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE, "管理助手暂未开放，请稍后再试", 503)
    return ConversationService(
        db,
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=config.tool_app_key_id,
    )


def client_for():
    try:
        return AdpChatClient.from_settings()
    except AdpCallError:
        raise AppError(
            ErrorCode.UPSTREAM_UNAVAILABLE, "管理助手暂未开放，请稍后再试", 503
        ) from None


@router.post("")
def create(
    body: ConversationCreate, actor: CurrentUserDep, sid: SessionIdDep, db: Db, request: Request
):
    client_for()
    service = service_for(db)
    row = service.create(
        actor.id, sid, college_id=int(body.college_id), semester_id=int(body.semester_id)
    )
    return success(
        service.read(
            row.id,
            actor.id,
            sid,
            college_id=int(body.college_id),
            semester_id=int(body.semester_id),
        ),
        getattr(request.state, "request_id", None),
    )


@router.get("/{conversation_id}")
def history(
    conversation_id: ConversationId,
    college_id: ScopeId,
    semester_id: ScopeId,
    actor: CurrentUserDep,
    sid: SessionIdDep,
    db: Db,
    request: Request,
    before_turn_id: BeforeId = None,
):
    result = service_for(db).read(
        conversation_id,
        actor.id,
        sid,
        college_id=college_id,
        semester_id=semester_id,
        before_turn_id=before_turn_id,
    )
    return success(result, getattr(request.state, "request_id", None))


@router.post("/{conversation_id}/messages")
def send(
    conversation_id: ConversationId,
    body: ConversationMessage,
    actor: CurrentUserDep,
    sid: SessionIdDep,
    db: Db,
    request: Request,
):
    client_for()
    service = service_for(db)
    scope = {"college_id": int(body.college_id), "semester_id": int(body.semester_id)}
    claim = service.enqueue(
        conversation_id, actor.id, sid, **scope, text=body.text, request_key=body.request_key
    )
    result = service.read(conversation_id, actor.id, sid, **scope)
    result["submitted_turn_id"] = str(claim.turn_id)
    return success(result, getattr(request.state, "request_id", None))
