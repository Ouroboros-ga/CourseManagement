"""Fixed chat queue transitions, sharing existing identity and conversation receipts."""

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError, ConflictError, ErrorCode, PermissionDeniedError
from app.modules.agent.chat_pool import capacity_guard
from app.modules.agent.conversation_models import AgentConversation, AgentTurn
from app.modules.agent.models import AgentRun


def _count(service, guard, states):
    conversations = select(AgentConversation.id).where(
        AgentConversation.environment == service.environment,
        AgentConversation.app_key_id == service.app_key_id,
    )
    return guard.count(
        service.db,
        select(func.count())
        .select_from(AgentTurn)
        .where(AgentTurn.conversation_id.in_(conversations), AgentTurn.state.in_(states)),
    )


def enqueue(
    service, conversation_id, user_id, session_id, *, college_id, semester_id, text, request_key
):
    from app.modules.agent.conversation_service import TurnClaim

    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 4000
        or not isinstance(request_key, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_key) is None
    ):
        raise AppError(ErrorCode.VALIDATION_ERROR, "对话内容或请求标识不合法", 422)
    text, request_key = text.strip(), request_key.lower()
    with capacity_guard(service.db, service.environment, service.app_key_id) as guard:
        if guard is None:
            raise AppError(ErrorCode.RATE_LIMITED, "当前对话请求较多，请稍后重试", 429)
        row = service._authorized(
            conversation_id, user_id, session_id, college_id=college_id, semester_id=semester_id
        )
        service._expire(row)
        input_hash = hashlib.sha256(text.encode()).hexdigest()
        previous = service.db.scalar(
            select(AgentTurn)
            .where(AgentTurn.conversation_id == row.id, AgentTurn.request_key == request_key)
            .execution_options(populate_existing=True)
        )
        if previous is not None:
            if previous.input_hash != input_hash:
                raise ConflictError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求标识的内容已变化")
            return TurnClaim(row.id, previous.id, previous.run_id)
        if row.state != "OPEN":
            raise ConflictError(message="上次对话结果不明或会话已关闭，请重新开始")
        if service.db.scalar(
            select(AgentTurn.id)
            .where(AgentTurn.conversation_id == row.id, AgentTurn.state.in_(["QUEUED", "SENDING"]))
            .limit(1)
        ):
            raise ConflictError(message="上一轮仍在排队或处理中，请先查询状态")
        count = service.db.scalar(
            select(func.count()).select_from(AgentTurn).where(AgentTurn.conversation_id == row.id)
        )
        if count >= service.MAX_TURNS:
            raise ConflictError(message="本会话已达轮次上限，请重新开始")
        if _count(service, guard, ["QUEUED"]) >= service.limits.max_queued:
            raise AppError(ErrorCode.RATE_LIMITED, "对话等待队列已满，请稍后重试", 429)
        run, _discarded_token = service.runs.issue_in_transaction(
            service.app_key_id, user_id, session_id, college_id=college_id, semester_id=semester_id
        )
        turn = AgentTurn(
            conversation_id=row.id,
            run_id=run.id,
            request_key=request_key,
            input_hash=input_hash,
            remote_request_id=uuid4().hex,
            state="QUEUED",
            attempt_token=None,
            deadline_at=utcnow() + timedelta(seconds=service.limits.max_wait_seconds),
            user_text=text,
        )
        service.db.add(turn)
        service.db.flush()
        service._retire(run.id)
        ticket = TurnClaim(row.id, turn.id, run.id)
        service.db.commit()
        return ticket


def claim_queued(service):
    from app.modules.agent.conversation_service import TurnClaim

    db = service.db
    with capacity_guard(db, service.environment, service.app_key_id) as guard:
        if guard is None:
            return None
        pool = select(AgentConversation.id).where(
            AgentConversation.environment == service.environment,
            AgentConversation.app_key_id == service.app_key_id,
        )
        expired = db.scalar(
            select(AgentTurn.conversation_id)
            .where(
                AgentTurn.conversation_id.in_(pool),
                AgentTurn.state.in_(["QUEUED", "SENDING"]),
                AgentTurn.deadline_at <= utcnow(),
            )
            .order_by(AgentTurn.id)
            .limit(1)
        )
        if expired is not None:
            row = db.scalar(
                select(AgentConversation)
                .where(AgentConversation.id == expired)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            service._expire(row)
        if _count(service, guard, ["SENDING", "UNCERTAIN"]) >= service.limits.max_active:
            db.commit()
            return None
        candidate = db.execute(
            select(AgentTurn.id, AgentTurn.conversation_id)
            .where(AgentTurn.conversation_id.in_(pool), AgentTurn.state == "QUEUED")
            .order_by(AgentTurn.id)
            .limit(1)
        ).first()
        if candidate is None:
            db.commit()
            return None
        turn_id, conversation_id = candidate
        row = db.scalar(
            select(AgentConversation)
            .where(AgentConversation.id == conversation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        turn = db.scalar(
            select(AgentTurn)
            .where(AgentTurn.id == turn_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if turn.state != "QUEUED":
            db.commit()
            return None
        if turn.deadline_at <= utcnow():
            service._expire(row)
            return None
        try:
            service._authorized(
                row.id,
                row.actor_user_id,
                row.source_session_id,
                college_id=row.college_id,
                semester_id=row.semester_id,
            )
            context = service.runs.restore(turn.run_id)
            run = db.get(AgentRun, turn.run_id)
            if (
                context.entry_kind != "MANAGEMENT"
                or context.college_id != row.college_id
                or context.semester_id != row.semester_id
                or run.app_key_id != service.app_key_id
            ):
                raise PermissionDeniedError()
            token = service.runs.rotate_in_transaction(
                turn.run_id, row.actor_user_id, row.source_session_id
            )
        except AppError:
            row = db.scalar(
                select(AgentConversation)
                .where(AgentConversation.id == conversation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            turn = db.scalar(
                select(AgentTurn)
                .where(AgentTurn.id == turn_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            row.state, turn.state, turn.error_code = "CLOSED", "FAILED", "CONTEXT_CHANGED"
            service._retire(turn.run_id)
            ticket = TurnClaim(row.id, turn.id, turn.run_id)
            db.commit()
            service.changed = True
            return ticket
        turn.state, turn.attempt_token = "SENDING", secrets.token_urlsafe(32)
        turn.deadline_at = utcnow() + timedelta(seconds=90)
        run.credential_expires_at = turn.deadline_at
        claim = TurnClaim(
            row.id,
            turn.id,
            run.id,
            row.remote_conversation_id,
            turn.remote_request_id,
            hashlib.sha256(row.remote_conversation_id.encode()).hexdigest(),
            turn.attempt_token,
            token,
            user_text=turn.user_text,
            college_id=row.college_id,
            semester_id=row.semester_id,
            business_date=(
                turn.created_at + timedelta(hours=get_settings().app_utc_offset_hours)
            ).date(),
        )
        db.commit()
        service.changed = True
        return claim
