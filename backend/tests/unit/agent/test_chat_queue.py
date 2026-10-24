from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.modules.agent.adp_schemas import AdpChatQueueLimits
from app.modules.agent.conversation_models import AgentTurn
from app.modules.agent.conversation_service import ConversationService
from app.modules.agent.models import AgentRun


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_conversations import fixture as conversation_fixture

    original = conversation_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def arrange(case, **limits):
    assert hasattr(ConversationService, "enqueue"), "Durable chat queue is missing"
    db = case[0][1]
    source = db.query(AgentRun).one()
    service = ConversationService(
        db,
        case[2].connections,
        environment="dev",
        app_key_id="management",
        limits=AdpChatQueueLimits(**limits),
    )
    scope = {"college_id": source.college_id, "semester_id": source.semester_id}
    rows = [service.create(case[1].id, source.source_session_id, **scope) for _ in range(2)]
    return service, rows, source, scope


def enqueue(case, service, row, source, scope, key="one"):
    return service.enqueue(
        row.id,
        case[1].id,
        source.source_session_id,
        **scope,
        text="排队中的合成问题",
        request_key=key,
    )


def test_enqueue_has_no_usable_credential_and_global_slot_is_claimed_fifo(case):
    service, rows, source, scope = arrange(case)
    first = enqueue(case, service, rows[0], source, scope)
    second = enqueue(case, service, rows[1], source, scope)
    assert not first.can_send and not second.can_send
    run = case[0][1].get(AgentRun, first.run_id)
    assert run.credential_expires_at <= utcnow()
    claim = service.claim_queued()
    assert claim.turn_id == first.turn_id and claim.can_send
    assert service.claim_queued() is None
    assert service.complete(claim, "第一轮完成")
    next_claim = service.claim_queued()
    assert next_claim.turn_id == second.turn_id and next_claim.can_send


def test_global_queue_bound_rejects_without_creating_another_run(case):
    service, rows, source, scope = arrange(case, max_queued=1)
    first = enqueue(case, service, rows[0], source, scope)
    count = case[0][1].query(AgentRun).count()
    assert enqueue(case, service, rows[0], source, scope).turn_id == first.turn_id
    with pytest.raises(AppError) as error:
        enqueue(case, service, rows[1], source, scope)
    assert error.value.http_status == 429
    assert case[0][1].query(AgentRun).count() == count


def test_uncertain_remote_call_retains_its_slot(case):
    service, rows, source, scope = arrange(case)
    enqueue(case, service, rows[0], source, scope)
    enqueue(case, service, rows[1], source, scope)
    claim = service.claim_queued()
    assert service.fail(claim, "CHAT_UPSTREAM_UNCERTAIN", ambiguous=True)
    assert service.claim_queued() is None
    assert case[0][1].get(AgentTurn, claim.turn_id).state == "UNCERTAIN"


def test_expired_wait_fails_without_sending_and_keeps_conversation_open(case):
    service, rows, source, scope = arrange(case)
    ticket = enqueue(case, service, rows[0], source, scope)
    turn = case[0][1].get(AgentTurn, ticket.turn_id)
    turn.deadline_at = utcnow() - timedelta(seconds=1)
    case[0][1].commit()
    claim = service.claim_queued()
    assert claim is None or not claim.can_send
    case[0][1].refresh(turn)
    assert turn.state == "FAILED" and turn.error_code == "CHAT_QUEUE_EXPIRED"
    assert rows[0].state == "OPEN"


def test_expired_inflight_is_uncertain_and_never_resent(case):
    service, rows, source, scope = arrange(case)
    enqueue(case, service, rows[0], source, scope)
    claim = service.claim_queued()
    turn = case[0][1].get(AgentTurn, claim.turn_id)
    turn.deadline_at = utcnow() - timedelta(seconds=1)
    case[0][1].commit()
    assert service.claim_queued() is None
    case[0][1].refresh(turn)
    assert turn.state == "UNCERTAIN"
    assert not service.complete(claim, "late result")


def test_authority_is_rechecked_after_waiting(case):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    service, rows, source, scope = arrange(case)
    ticket = enqueue(case, service, rows[0], source, scope)
    for binding in case[0][1].query(TeacherCollegeBinding).all():
        case[0][1].delete(binding)
    case[0][1].commit()
    claim = service.claim_queued()
    assert not claim.can_send
    turn = case[0][1].get(AgentTurn, ticket.turn_id)
    assert turn.state == "FAILED" and turn.reply is None


def test_claim_releases_transaction_before_network_even_when_orm_expires(case):
    service, rows, source, scope = arrange(case)
    enqueue(case, service, rows[0], source, scope)
    db = case[0][1]
    db.expire_on_commit = True
    try:
        claim = service.claim_queued()
        assert claim.can_send and not db.in_transaction()
    finally:
        db.expire_on_commit = False
