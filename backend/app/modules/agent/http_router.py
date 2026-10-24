import json

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.common.responses import success
from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode, NotFoundError
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.run_context import RunService

router = APIRouter(prefix="/agent-tools/v1", tags=["agent-tools"])
MAX_BODY = 256 * 1024


@router.post("/calls/{tool_name}")
async def call_tool(tool_name: str, request: Request):
    # Stream count rather than trusting Content-Length. Parse only after the bound is checked.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请求内容过大", 413)
    try:
        payload = json.loads(body)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"arguments"}
            or not isinstance(payload["arguments"], dict)
        ):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise AppError(ErrorCode.VALIDATION_ERROR, "需要 arguments 对象", 422) from None
    # A Session is created, used and closed in the same synchronous thread.
    return await run_in_threadpool(
        _execute,
        tool_name,
        payload["arguments"],
        request.headers.get("X-Tool-App-Key", ""),
        request.headers.get("X-Agent-Run-Token", ""),
        getattr(request.state, "request_id", None),
    )


def _execute(tool_name, arguments, app_key, run_token, request_id):
    from app.core.database import get_session_factory

    # Existing identity/domain services own their commits; don't wrap them in begin().
    with get_session_factory()() as db:
        return execute_with_session(db, tool_name, arguments, app_key, run_token, request_id)


def execute_with_session(db, tool_name, arguments, app_key, run_token, request_id):
    settings = get_settings()
    if not settings.agent_tools_enabled:
        raise NotFoundError()
    context = RunService(db, settings.agent_tool_connections, environment=settings.app_env).resolve(
        app_key, run_token
    )
    result = invoke_tool(db, context, tool_name, arguments)
    return success(result.model_dump(mode="json"), request_id)
