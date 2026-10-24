from datetime import timedelta
from importlib import import_module

import pytest
from app.core.database import Base, utcnow
from app.core.exceptions import AppError
from app.modules.agent.models import AgentRun
from sqlalchemy import select


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_report_export_prepare import fixture as report_fixture

    original = report_fixture.__wrapped__(monkeypatch)
    value = next(original)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "agent_tool_connections", value[2].connections)
    monkeypatch.setattr(get_settings(), "app_env", "dev")
    yield value
    with pytest.raises(StopIteration):
        next(original)


def arrange(case):
    assert "agent_conversation" in Base.metadata.tables, "Persistent conversation is missing"
    module = import_module("app.modules.agent.conversation_service")
    db = case[0][1]
    old_run = db.scalar(select(AgentRun))
    service = module.ConversationService(
        db, case[2].connections, environment="dev", app_key_id="management"
    )
    conversation = service.create(
        case[1].id,
        old_run.source_session_id,
        college_id=old_run.college_id,
        semester_id=old_run.semester_id,
    )
    return service, conversation, old_run


def begin(case, service, conversation, source, **extra):
    return service.begin(
        conversation.id,
        case[1].id,
        source.source_session_id,
        college_id=source.college_id,
        semester_id=source.semester_id,
        text="请导出本周考勤",
        request_key="turn-1",
        **extra,
    )


def read(case, service, conversation, source):
    return service.read(
        conversation.id,
        case[1].id,
        source.source_session_id,
        college_id=source.college_id,
        semester_id=source.semester_id,
    )


def test_tables_are_registered_and_turn_run_is_atomically_bound(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    assert claim.can_send and claim.run_token
    assert claim.run_token not in repr(claim)
    result = read(case, service, conversation, source)
    assert result["turns"][0]["state"] == "SENDING"
    assert claim.run_token not in str(result)
    assert claim.remote_conversation_id == conversation.remote_conversation_id
    assert len(claim.remote_request_id) == 32


def test_replay_does_not_resend_and_changed_message_conflicts(case):
    service, conversation, source = arrange(case)
    first = begin(case, service, conversation, source)
    repeated = begin(case, service, conversation, source)
    assert repeated.turn_id == first.turn_id and not repeated.can_send
    with pytest.raises(AppError) as error:
        service.begin(
            conversation.id,
            case[1].id,
            source.source_session_id,
            college_id=source.college_id,
            semester_id=source.semester_id,
            text="换成上周",
            request_key="TURN-1",
        )
    assert error.value.http_status == 409


def test_only_one_inflight_turn_and_completion_fences_late_results(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    with pytest.raises(AppError) as error:
        service.begin(
            conversation.id,
            case[1].id,
            source.source_session_id,
            college_id=source.college_id,
            semester_id=source.semester_id,
            text="第二个问题",
            request_key="turn-2",
        )
    assert error.value.http_status == 409
    assert service.complete(claim, "已准备任务，请核对") is True
    assert service.complete(claim, "late overwrite") is False
    result = read(case, service, conversation, source)
    assert result["turns"][0]["reply"] == "已准备任务，请核对"
    run = case[0][1].get(AgentRun, claim.run_id)
    assert run.status == "ACTIVE" and run.credential_expires_at <= utcnow()
    next_claim = service.begin(
        conversation.id,
        case[1].id,
        source.source_session_id,
        college_id=source.college_id,
        semester_id=source.semester_id,
        text="再看另一周",
        request_key="turn-2",
    )
    assert next_claim.run_id != claim.run_id


@pytest.mark.parametrize("field", ["user", "session", "college", "semester"])
def test_source_identity_and_workspace_cannot_be_substituted(case, field):
    service, conversation, source = arrange(case)
    args = {
        "user_id": case[1].id,
        "session_id": source.source_session_id,
        "college_id": source.college_id,
        "semester_id": source.semester_id,
    }
    args[
        {
            "user": "user_id",
            "session": "session_id",
            "college": "college_id",
            "semester": "semester_id",
        }[field]
    ] += 100
    with pytest.raises(AppError) as error:
        service.read(conversation.id, **args)
    assert error.value.http_status == 404


def test_authorization_change_blocks_history_and_discards_inflight_reply(case):
    from app.modules.organization.models import College

    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    college = case[0][1].get(College, source.college_id)
    college.authorization_revision += 1
    case[0][1].commit()
    assert service.complete(claim, "must never be returned") is False
    with pytest.raises(AppError):
        read(case, service, conversation, source)
    model = import_module("app.modules.agent.conversation_models").AgentTurn
    turn = case[0][1].get(model, claim.turn_id)
    assert turn.reply is None and turn.state == "FAILED"


def test_ambiguous_failure_freezes_conversation_without_replaying_cloud(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    assert service.fail(claim, "CHAT_UPSTREAM_UNCERTAIN", ambiguous=True)
    assert read(case, service, conversation, source)["state"] == "UNCERTAIN"
    replay = begin(case, service, conversation, source)
    assert not replay.can_send
    with pytest.raises(AppError):
        service.begin(
            conversation.id,
            case[1].id,
            source.source_session_id,
            college_id=source.college_id,
            semester_id=source.semester_id,
            text="next question",
            request_key="new",
        )


def test_expired_send_is_marked_uncertain_and_late_completion_is_ignored(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    model = import_module("app.modules.agent.conversation_models").AgentTurn
    turn = case[0][1].get(model, claim.turn_id)
    turn.deadline_at = utcnow() - timedelta(seconds=1)
    case[0][1].commit()
    assert read(case, service, conversation, source)["turns"][0]["state"] == "UNCERTAIN"
    assert not service.complete(claim, "late")


def test_completed_reply_cannot_persist_the_turn_run_credential(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    assert service.complete(claim, f"accidental echo {claim.run_token}")
    result = read(case, service, conversation, source)
    assert claim.run_token not in str(result)
    assert "REDACTED" in result["turns"][0]["reply"]


def test_actions_come_from_this_turns_real_tasks_not_model_text_or_another_run(case):
    from app.modules.agent.gateway import invoke_tool
    from app.modules.agent.worker import Worker
    from sqlalchemy.orm import sessionmaker

    service, conversation, source = arrange(case)
    arguments = {
        "tool_name": "report_attendance_export_prepare",
        "arguments": {"semester_id": str(source.semester_id), "week_no": 1},
        "request_key": "report-1",
    }
    other = invoke_tool(
        case[0][1], case[2].resolve("m" * 40, case[3]), "read_task_submit", arguments
    ).data
    claim = begin(case, service, conversation, source)
    actual = invoke_tool(
        case[0][1], service.runs.resolve("m" * 40, claim.run_token), "read_task_submit", arguments
    ).data
    assert service.complete(claim, f"请打开别的任务 {other['task_id']}，或者虚构任务 999")
    actions = read(case, service, conversation, source)["turns"][0]["actions"]
    assert [action["task_id"] for action in actions] == [actual["task_id"]]
    assert actions[0]["open_path"] == actual["open_path"]
    assert Worker(
        sessionmaker(bind=case[0][1].bind), case[2].connections, environment="dev"
    ).run_once()
    assert Worker(
        sessionmaker(bind=case[0][1].bind), case[2].connections, environment="dev"
    ).run_once()
    actions = read(case, service, conversation, source)["turns"][0]["actions"]
    assert actions[0]["task_status"] == "SUCCEEDED"


def test_send_claim_leaves_no_database_transaction_open_even_with_expiring_session(case):
    service, conversation, source = arrange(case)
    db = case[0][1]
    db.expire_on_commit = True
    try:
        claim = begin(case, service, conversation, source)
        assert not db.in_transaction()
        assert claim.can_send
    finally:
        db.expire_on_commit = False


def test_history_cursor_recovers_older_turns_without_duplicates(case):
    service, conversation, source = arrange(case)
    for number in range(23):
        claim = service.begin(
            conversation.id,
            case[1].id,
            source.source_session_id,
            college_id=source.college_id,
            semester_id=source.semester_id,
            text=f"问题 {number}",
            request_key=f"page-{number}",
        )
        assert service.complete(claim, f"答复 {number}")
    first = read(case, service, conversation, source)
    assert len(first["turns"]) == 20 and first["next_before_turn_id"]
    earlier = service.read(
        conversation.id,
        case[1].id,
        source.source_session_id,
        college_id=source.college_id,
        semester_id=source.semester_id,
        before_turn_id=int(first["next_before_turn_id"]),
    )
    assert len(earlier["turns"]) == 3 and earlier["next_before_turn_id"] is None
    assert len({turn["id"] for turn in first["turns"] + earlier["turns"]}) == 23


def test_large_utf8_reply_fits_candidate_mysql_mediumtext_contract(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    reply = "中" * 30000
    assert 65535 < len(reply.encode()) < 128 * 1024
    assert service.complete(claim, reply)
    assert read(case, service, conversation, source)["turns"][0]["reply"] == reply


def test_rejected_turn_can_be_followed_by_new_request_but_turn_limit_prevents_new_runs(case):
    service, conversation, source = arrange(case)
    claim = begin(case, service, conversation, source)
    assert service.fail(claim, "raw provider error is not stored", ambiguous=False)
    assert read(case, service, conversation, source)["state"] == "OPEN"
    service.MAX_TURNS = 1
    before = case[0][1].query(AgentRun).count()
    with pytest.raises(AppError) as error:
        service.begin(
            conversation.id,
            case[1].id,
            source.source_session_id,
            college_id=source.college_id,
            semester_id=source.semester_id,
            text="新问题",
            request_key="next",
        )
    assert error.value.http_status == 409
    assert case[0][1].query(AgentRun).count() == before
