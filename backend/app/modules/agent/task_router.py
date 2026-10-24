from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.agent.schemas import TaskSubmit
from app.modules.agent.task_service import TaskService
from app.modules.identity.deps import CurrentUserDep, SessionIdDep


def require_enabled():
    if not get_settings().agent_tools_enabled:
        raise NotFoundError()


router = APIRouter(
    prefix="/assistant/tasks", tags=["agent-tasks"], dependencies=[Depends(require_enabled)]
)
Db = Annotated[Session, Depends(get_db)]
TaskId = Annotated[int, Path(gt=0, le=2**63 - 1)]


def service(db):
    settings = get_settings()
    return TaskService(db, settings.agent_tool_connections, environment=settings.app_env)


@router.post("")
def submit(body: TaskSubmit, actor: CurrentUserDep, sid: SessionIdDep, db: Db, request: Request):
    task = service(db).submit(
        int(body.run_id), actor.id, sid, body.tool_name, body.arguments, body.request_key
    )
    db.commit()
    return success(
        {"task_id": str(task.id), "status": task.status}, getattr(request.state, "request_id", None)
    )


@router.get("/{task_id}")
def status(task_id: TaskId, actor: CurrentUserDep, db: Db, request: Request):
    return success(service(db).read(task_id, actor.id), getattr(request.state, "request_id", None))


@router.post("/{task_id}/cancel")
def cancel(task_id: TaskId, actor: CurrentUserDep, db: Db, request: Request):
    service(db).cancel(task_id, actor.id)
    return success({"task_id": str(task_id)}, getattr(request.state, "request_id", None))
