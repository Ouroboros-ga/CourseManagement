"""ADP v2 chat transport. Final reply text is data, never a business execution receipt."""

import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import httpx

from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.adp_schemas import AdpChatConfiguration

ENDPOINT = "https://wss.lke.cloud.tencent.com/adp/v2/chat"
MAX_RESPONSE_BYTES = 512 * 1024
MAX_REPLY_BYTES = 128 * 1024
MAX_EVENTS = 4096
_identifier = re.compile(r"[A-Za-z0-9_-]{32,64}\Z")
_token = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")


@dataclass(frozen=True)
class AdpChatReply:
    conversation_id: str
    request_id: str
    text: str = field(repr=False)


def _bad_response():
    return AdpCallError("CHAT_UPSTREAM_BAD_RESPONSE", ambiguous=True)


def _events(chunks: Iterable[bytes], deadline: float, clock: Callable[[], float]):
    buffer = b""
    lines: list[str] = []
    name, received, count = "", 0, 0

    def decode():
        if name and name not in {"response.completed", "error"}:
            return None
        value = json.loads("\n".join(lines))
        if not isinstance(value, dict) or (name and value.get("Type") != name):
            raise _bad_response()
        return value

    for chunk in chunks:
        if clock() > deadline:
            raise AdpCallError("CHAT_TIME_BUDGET", ambiguous=True)
        received += len(chunk)
        if received > MAX_RESPONSE_BYTES:
            raise AdpCallError("CHAT_RESPONSE_TOO_LARGE", ambiguous=True)
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            line = raw.rstrip(b"\r").decode("utf-8")
            if not line:
                if lines:
                    count += 1
                    if count > MAX_EVENTS:
                        raise AdpCallError("CHAT_EVENT_LIMIT", ambiguous=True)
                    value = decode()
                    if value is not None:
                        yield value
                name, lines = "", []
            elif line.startswith("event:"):
                name = line[6:].lstrip(" ")
            elif line.startswith("data:"):
                lines.append(line[5:].removeprefix(" "))
            # Comments, id and retry fields cannot change local execution behavior.
    if buffer or lines:
        # Do not treat a truncated final event as a successful response.
        raise AdpCallError("CHAT_STREAM_INCOMPLETE", ambiguous=True)


def _reply_text(value: dict, conversation_id: str) -> str:
    response = value.get("Response")
    if (
        not isinstance(response, dict)
        or response.get("ConversationId") != conversation_id
        or response.get("Role") != "assistant"
        or response.get("Status") != "success"
        or not isinstance(response.get("Messages"), list)
    ):
        raise _bad_response()
    parts = []
    for message in response["Messages"]:
        if not isinstance(message, dict):
            raise _bad_response()
        if message.get("Type") != "reply":
            continue
        if message.get("Status") != "success" or not isinstance(message.get("Contents"), list):
            raise _bad_response()
        text = []
        for content in message["Contents"]:
            if not isinstance(content, dict):
                raise _bad_response()
            if content.get("Type") == "text":
                if not isinstance(content.get("Text"), str):
                    raise _bad_response()
                text.append(content["Text"])
        parts.append("".join(text))
    result = "\n".join(parts)
    if len(result.encode()) > MAX_REPLY_BYTES:
        raise AdpCallError("CHAT_RESPONSE_TOO_LARGE", ambiguous=True)
    return result


class AdpChatClient:
    @classmethod
    def from_settings(cls, settings=None):
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        config = settings.agent_management_chat_config
        if not settings.agent_tools_enabled or not settings.agent_adp_enabled or config is None:
            raise AdpCallError("CHAT_NOT_CONFIGURED")
        if not config.header_binding_verified:
            raise AdpCallError("HEADER_BINDING_UNVERIFIED")
        if not any(
            connection.app_key_id == config.tool_app_key_id
            and connection.environment == settings.app_env
            and connection.entry_kind == "MANAGEMENT"
            and connection.workflow_kind is None
            for connection in settings.agent_tool_connections
        ):
            raise AdpCallError("WORKFLOW_APPLICATION_CONFLICT")
        return cls(config)

    def __init__(
        self, config: AdpChatConfiguration, *, client_factory=httpx.Client, clock=time.monotonic
    ):
        self.config, self.client_factory, self.clock = config, client_factory, clock

    def chat(
        self, text: str, *, conversation_id: str, request_id: str, user_id: str, run_token: str
    ) -> AdpChatReply:
        if not self.config.header_binding_verified:
            raise AdpCallError("HEADER_BINDING_UNVERIFIED")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 4000
            or any(
                not isinstance(value, str) or _identifier.fullmatch(value) is None
                for value in (conversation_id, request_id, user_id)
            )
            or not isinstance(run_token, str)
            or _token.fullmatch(run_token) is None
        ):
            raise AdpCallError("INVALID_LOCAL_INPUT")
        app_key = self.config.app_key.get_secret_value()
        payload = {
            "AppKey": app_key,
            "ConversationId": conversation_id,
            "RequestId": request_id,
            "UserId": user_id,
            "VisitorId": user_id,
            "Contents": [
                {"Type": "text", "Text": text},
                {"Type": "custom_variables", "CustomVariables": {"agent_run_token": run_token}},
            ],
            "Incremental": True,
            "Stream": "enable",
            "WorkflowStatus": "enable",
        }
        deadline = self.clock() + self.config.timeout_seconds
        timeout = httpx.Timeout(
            connect=min(5, self.config.timeout_seconds),
            read=min(10, self.config.timeout_seconds),
            write=min(10, self.config.timeout_seconds),
            pool=min(5, self.config.timeout_seconds),
        )
        final = None
        try:
            with (
                self.client_factory(
                    timeout=timeout, follow_redirects=False, trust_env=False
                ) as client,
                client.stream(
                    "POST", ENDPOINT, json=payload, headers={"Accept": "text/event-stream"}
                ) as response,
            ):
                if response.status_code != 200:
                    raise AdpCallError(
                        "CHAT_UPSTREAM_REJECTED", ambiguous=response.status_code >= 500
                    )
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "text/event-stream"
                ):
                    raise _bad_response()
                for value in _events(response.iter_bytes(), deadline, self.clock):
                    if value.get("Type") == "error":
                        raise AdpCallError("CHAT_UPSTREAM_ERROR", ambiguous=True)
                    if value.get("Type") == "response.completed":
                        if final is not None:
                            raise _bad_response()
                        final = _reply_text(value, conversation_id)
        except AdpCallError:
            raise
        except Exception:
            # Exception text and raw SSE can contain app keys, run tokens or private material.
            raise AdpCallError("CHAT_UPSTREAM_UNCERTAIN", ambiguous=True) from None
        if final is None:
            raise AdpCallError("CHAT_STREAM_INCOMPLETE", ambiguous=True)
        for secret in sorted({app_key, run_token}, key=len, reverse=True):
            final = final.replace(secret, "[REDACTED]")
        return AdpChatReply(conversation_id, request_id, final)
