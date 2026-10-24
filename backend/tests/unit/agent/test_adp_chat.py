import json

import httpx
import pytest
from app.modules.agent import adp_schemas
from app.modules.agent.adp_client import AdpCallError

CONVERSATION = "c" * 32
REQUEST = "r" * 32
USER = "u" * 32
TOKEN = "t" * 43
KEY = "synthetic-platform-app-key"


def config(**extra):
    cls = getattr(adp_schemas, "AdpChatConfiguration", None)
    assert cls is not None, "The interactive SSE configuration is not implemented"
    return cls(app_key=KEY, tool_app_key_id="management", header_binding_verified=True, **extra)


def event(kind, **payload):
    data = json.dumps({"Type": kind, **payload}, ensure_ascii=False)
    return f"event: {kind}\ndata: {data}\n\n".encode()


def completed(text="合成回复", **extra):
    return event(
        "response.completed",
        Response={
            "Role": "assistant",
            "ConversationId": CONVERSATION,
            "Status": "success",
            "Messages": [
                {
                    "Type": "thought",
                    "Status": "success",
                    "Contents": [{"Type": "text", "Text": "private thought"}],
                },
                {
                    "Type": "reply",
                    "Status": "success",
                    "Contents": [
                        {"Type": "text", "Text": text},
                        {"Type": "widget", "Widget": {"View": "untrusted script"}},
                    ],
                },
            ],
            "Procedures": [{"Input": TOKEN, "Output": KEY}],
            **extra,
        },
    )


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def arrange(
    content=None,
    *,
    chunks=None,
    status=200,
    content_type="text/event-stream",
    failure=None,
    configuration=None,
    clock=None,
):
    from app.modules.agent.adp_chat import AdpChatClient

    calls = []

    def handler(request):
        calls.append(request)
        if failure:
            raise failure
        return httpx.Response(
            status,
            headers={"content-type": content_type},
            stream=Chunks(chunks if chunks is not None else [content or completed()]),
        )

    client = AdpChatClient(
        configuration or config(),
        client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
        **({"clock": clock} if clock else {}),
    )
    return client, calls


def chat(client, **extra):
    return client.chat(
        "请核对合成资料",
        conversation_id=CONVERSATION,
        request_id=REQUEST,
        user_id=USER,
        run_token=TOKEN,
        **extra,
    )


def test_interactive_configuration_has_a_separate_default_closed_binding_gate():
    cls = getattr(adp_schemas, "AdpChatConfiguration", None)
    assert cls is not None, "The interactive SSE configuration is not implemented"
    value = cls(app_key=KEY, tool_app_key_id="management")
    assert value.header_binding_verified is False
    assert KEY not in repr(value)


def test_request_uses_documented_fixed_endpoint_and_separate_custom_variables():
    client, calls = arrange()
    reply = chat(client)
    assert reply.text == "合成回复"
    assert reply.conversation_id == CONVERSATION
    assert len(calls) == 1
    assert str(calls[0].url) == "https://wss.lke.cloud.tencent.com/adp/v2/chat"
    body = json.loads(calls[0].content)
    assert body["AppKey"] == KEY
    assert body["ConversationId"] == CONVERSATION and body["RequestId"] == REQUEST
    assert body["UserId"] == USER and body["VisitorId"] == USER
    assert body["Contents"] == [
        {"Type": "text", "Text": "请核对合成资料"},
        {"Type": "custom_variables", "CustomVariables": {"agent_run_token": TOKEN}},
    ]
    assert "SystemRole" not in body
    assert TOKEN not in body["Contents"][0]["Text"]


def test_final_reply_is_authoritative_and_thought_widgets_and_procedures_are_ignored():
    content = event("text.delta", MessageId="thought-1", ContentIndex=0, Text="private thought")
    content += event("text.replace", MessageId="reply-1", ContentIndex=0, Text="outdated draft")
    content += completed("最终答复")
    client, _ = arrange(content)
    assert chat(client).text == "最终答复"


def test_utf8_and_sse_fields_survive_single_byte_network_chunks_and_comments():
    body = b": heartbeat\r\n\r\n" + completed("中文回复与换行\n第二行")
    client, _ = arrange(chunks=[body[index : index + 1] for index in range(len(body))])
    assert chat(client).text == "中文回复与换行\n第二行"


def test_known_credentials_are_redacted_after_full_message_assembly():
    body = completed(f"{TOKEN} / {KEY}")
    client, _ = arrange(chunks=[body[:50], body[50:]])
    reply = chat(client)
    assert TOKEN not in reply.text and KEY not in reply.text
    assert "REDACTED" in reply.text
    assert KEY not in repr(reply) and TOKEN not in repr(reply)


@pytest.mark.parametrize(
    "extra", [{"ConversationId": "other-conversation"}, {"Status": "failed"}, {"Role": "user"}]
)
def test_unmatched_or_unsuccessful_completion_is_never_accepted(extra):
    client, calls = arrange(completed(**extra))
    with pytest.raises(AdpCallError):
        chat(client)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        event("text.delta", MessageId="reply-1", ContentIndex=0, Text="partial reply"),
        event("error", Error={"Code": 1, "Message": TOKEN + KEY}),
        b"event: response.completed\ndata: broken-json\n\n",
        b"event: response.completed\ndata: \xff\n\n",
        completed() + completed(),
    ],
)
def test_incomplete_malformed_error_or_duplicate_completion_is_sanitized(body):
    client, calls = arrange(body)
    with pytest.raises(AdpCallError) as error:
        chat(client)
    assert TOKEN not in str(error.value) and KEY not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,content_type",
    [
        (302, "text/event-stream"),
        (401, "text/event-stream"),
        (503, "text/event-stream"),
        (200, "application/json"),
    ],
)
def test_redirect_http_failures_and_wrong_content_type_are_not_retried(status, content_type):
    client, calls = arrange(status=status, content_type=content_type)
    with pytest.raises(AdpCallError):
        chat(client)
    assert len(calls) == 1


def test_network_error_is_ambiguous_and_never_retried_or_echoed():
    client, calls = arrange(failure=httpx.ReadTimeout(TOKEN + KEY))
    with pytest.raises(AdpCallError) as error:
        chat(client)
    assert error.value.ambiguous and not error.value.retryable
    assert TOKEN not in str(error.value) and KEY not in str(error.value)
    assert len(calls) == 1


def test_unverified_header_binding_fails_before_network():
    from app.modules.agent.adp_chat import AdpChatClient

    cls = adp_schemas.AdpChatConfiguration
    client, calls = arrange(configuration=cls(app_key=KEY, tool_app_key_id="management"))
    assert isinstance(client, AdpChatClient)
    with pytest.raises(AdpCallError) as error:
        chat(client)
    assert error.value.code == "HEADER_BINDING_UNVERIFIED" and not calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversation_id", "short"),
        ("request_id", "bad space"),
        ("user_id", "u"),
        ("run_token", "bad token"),
    ],
)
def test_identity_fields_are_validated_before_network(field, value):
    client, calls = arrange()
    params = dict(conversation_id=CONVERSATION, request_id=REQUEST, user_id=USER, run_token=TOKEN)
    params[field] = value
    with pytest.raises(AdpCallError):
        client.chat("合成请求", **params)
    assert not calls


def test_event_and_response_limits_stop_a_large_stream():
    client, calls = arrange(b"data: " + b"x" * (512 * 1024 + 1))
    with pytest.raises(AdpCallError):
        chat(client)
    assert len(calls) == 1


def test_total_deadline_stops_a_slow_stream_without_retry():
    ticks = iter([0.0, 100.0])
    client, calls = arrange(clock=lambda: next(ticks, 100.0))
    with pytest.raises(AdpCallError):
        chat(client)
    assert len(calls) == 1


def test_settings_factory_is_closed_without_both_flags_and_management_connection():
    from hashlib import sha256
    from types import SimpleNamespace

    from app.modules.agent.adp_chat import AdpChatClient
    from app.modules.agent.schemas import AppConnection

    settings = SimpleNamespace(
        agent_tools_enabled=True,
        agent_adp_enabled=True,
        agent_management_chat_config=config(),
        app_env="dev",
        agent_tool_connections=[
            AppConnection(
                app_key_id="management",
                environment="dev",
                entry_kind="MANAGEMENT",
                key_digest=sha256(b"m" * 40).hexdigest(),
            )
        ],
    )
    assert isinstance(AdpChatClient.from_settings(settings), AdpChatClient)
    for field, value in [
        ("agent_tools_enabled", False),
        ("agent_adp_enabled", False),
        ("agent_management_chat_config", None),
        ("agent_tool_connections", []),
        ("app_env", "prod"),
    ]:
        invalid = SimpleNamespace(**{**vars(settings), field: value})
        with pytest.raises(AdpCallError):
            AdpChatClient.from_settings(invalid)


def test_configuration_cannot_redirect_requests_or_expose_secret_in_validation_errors():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        config(endpoint="https://untrusted.invalid")
    assert KEY not in str(error.value)


def test_event_limit_stops_many_individually_valid_events():
    client, _ = arrange(event("text.delta", MessageId="reply-1", ContentIndex=0, Text="x") * 4097)
    with pytest.raises(AdpCallError) as error:
        chat(client)
    assert error.value.code == "CHAT_EVENT_LIMIT"


@pytest.mark.parametrize("text", ["", "  ", "x" * 4001, None])
def test_blank_or_oversized_questions_never_reach_network(text):
    client, calls = arrange()
    with pytest.raises(AdpCallError) as error:
        client.chat(
            text, conversation_id=CONVERSATION, request_id=REQUEST, user_id=USER, run_token=TOKEN
        )
    assert error.value.code == "INVALID_LOCAL_INPUT" and not calls


def test_transport_logs_never_include_request_credentials_or_error_body(caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    client, _ = arrange(event("error", Error={"Message": KEY + TOKEN}))
    with pytest.raises(AdpCallError):
        chat(client)
    assert KEY not in caplog.text and TOKEN not in caplog.text


def test_management_business_context_is_separate_from_the_question_text():
    from datetime import date

    from app.modules.agent import schemas

    cls = getattr(schemas, "ManagementChatContext", None)
    assert cls is not None, "Trusted business context has not been implemented"
    context = cls(college_id="1", semester_id="2", business_date=date(2026, 10, 25))
    client, calls = arrange()
    chat(client, business_context=context)
    body = json.loads(calls[0].content)
    variables = body["Contents"][1]["CustomVariables"]
    assert variables == {
        "agent_run_token": TOKEN,
        "college_id": "1",
        "semester_id": "2",
        "business_date": "2026-10-25",
        "timezone": "Asia/Shanghai",
    }
    assert body["Contents"][0]["Text"] == "请核对合成资料"
