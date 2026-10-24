"""Stateless MCP transport; per-request credentials never enter tool arguments."""

import json
from contextvars import ContextVar

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.run_context import RunContext, RunService

_identity: ContextVar[RunContext] = ContextVar("agent_mcp_identity")
_credentials: ContextVar[tuple[str, str]] = ContextVar("agent_mcp_credentials")


def with_session(callback):
    from app.core.database import get_session_factory

    with get_session_factory()() as db:
        return callback(db)


def resolve(app_key, token):
    settings = get_settings()
    return with_session(
        lambda db: RunService(
            db, settings.agent_tool_connections, environment=settings.app_env
        ).resolve(app_key, token)
    )


class AgentMCPServer(MCPServer):
    async def list_tools(self) -> list[Tool]:
        context = _identity.get()
        return [
            Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_model.model_json_schema(),
            )
            for spec in ToolRegistry().list_for(context.entry_kind, context.workflow_kind)
        ]

    async def call_tool(self, name, arguments, context=None):
        key, token = _credentials.get()

        def execute(db):
            settings = get_settings()
            identity = RunService(
                db, settings.agent_tool_connections, environment=settings.app_env
            ).resolve(key, token)
            return invoke_tool(db, identity, name, arguments).model_dump(mode="json")

        try:
            result = await run_in_threadpool(with_session, execute)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
            )
        except AppError as error:
            result = {
                "status": "FAILED",
                "error_code": error.code.value,
                "message": error.message,
                "retryable": False,
            }
            return CallToolResult(
                content=[TextContent(type="text", text=error.message)],
                structuredContent=result,
                isError=True,
            )


class AuthenticatedMCP:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        if not settings.agent_tools_enabled or not settings.agent_mcp_enabled:
            return await JSONResponse({"code": "NOT_FOUND"}, status_code=404)(scope, receive, send)
        headers = Headers(scope=scope)
        key, token = headers.get("X-Tool-App-Key", ""), headers.get("X-Agent-Run-Token", "")
        try:
            identity = await run_in_threadpool(resolve, key, token)
        except AppError as error:
            return await JSONResponse(
                {"code": error.code.value, "message": error.message}, status_code=error.http_status
            )(scope, receive, send)
        identity_token = _identity.set(identity)
        credential_token = _credentials.set((key, token))
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials.reset(credential_token)
            _identity.reset(identity_token)


def create_mcp_app():
    settings = get_settings()
    server = AgentMCPServer("course-agent-tools")
    app = server.streamable_http_app(
        streamable_http_path="/agent-tools",
        stateless_http=True,
        json_response=True,
        max_request_body_size=256 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.agent_mcp_allowed_hosts,
            allowed_origins=settings.agent_mcp_allowed_origins,
        ),
    )
    return AuthenticatedMCP(app), server
