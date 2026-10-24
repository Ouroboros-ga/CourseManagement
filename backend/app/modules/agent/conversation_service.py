"""Conversation admission and receipts; no remote calls while database locks are held."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import iso_utc, utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.academic.models import Semester
from app.modules.agent.conversation_models import AgentConversation, AgentTurn
from app.modules.agent.models import AgentJob, AgentRun, AgentTask
from app.modules.agent.read_task_submit import PAGES, task_handoff
from app.modules.agent.run_context import RunContext, RunService
from app.modules.agent.task_service import digest, visibility_hash
from app.modules.organization.models import College
from app.modules.organization.service import atomic_write


@dataclass(frozen=True)
class TurnClaim:
    conversation_id: int
    turn_id: int
    run_id: int
    remote_conversation_id: str | None = None
    remote_request_id: str | None = None
    user_ref: str | None = None
    attempt_token: str | None = field(default=None, repr=False)
    run_token: str | None = field(default=None, repr=False)
    user_text: str = field(default="", repr=False)
    college_id: int | None = None
    semester_id: int | None = None
    business_date: date | None = None

    @property
    def can_send(self):
        return self.run_token is not None


class ConversationService:
    MAX_TURNS = 100

    def __init__(self, db, connections, *, environment, app_key_id, limits=None):
        self.db, self.environment, self.app_key_id = db, environment, app_key_id
        self.runs = RunService(db, connections, environment=environment)
        self.limits = limits or get_settings().agent_chat_queue_limits
        self.changed = False

    def _scope_hash(self, actor, cid, sid):
        connection = self.runs._connection(self.app_key_id)
        if connection.entry_kind != "MANAGEMENT":
            raise PermissionDeniedError("该应用不是管理交互应用")
        semester = self.db.get(Semester, sid, populate_existing=True)
        college = self.db.get(College, cid, populate_existing=True)
        if semester is None or college is None:
            raise NotFoundError()
        context = RunContext("0", "MANAGEMENT", actor, cid, sid)
        scopes = {}
        for name in (
            "report_attendance_summary",
            "import_preview_review",
            "responsibility_tasks_list",
        ):
            try:
                scopes[name] = visibility_hash(self.db, context, name)
            except PermissionDeniedError:
                scopes[name] = None
        if not any(scopes.values()):
            raise PermissionDeniedError("当前没有可使用的管理助手业务范围")
        return digest(
            {
                "scopes": scopes,
                "semester": sid,
                "semester_status": semester.status,
                "configuration": college.configuration_revision,
            }
        )

    @atomic_write
    def create(self, user_id, session_id, *, college_id, semester_id):
        actor = self.runs._actor(user_id, session_id, touch_session=False)
        scope_hash = self._scope_hash(actor, college_id, semester_id)
        row = AgentConversation(
            actor_user_id=user_id,
            source_session_id=session_id,
            college_id=college_id,
            semester_id=semester_id,
            environment=self.environment,
            app_key_id=self.app_key_id,
            remote_conversation_id=uuid4().hex,
            scope_hash=scope_hash,
            state="OPEN",
            expires_at=utcnow() + timedelta(hours=24),
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _authorized(self, conversation_id, user_id, session_id, *, college_id, semester_id):
        row = self.db.scalar(
            select(AgentConversation)
            .where(
                AgentConversation.id == conversation_id,
                AgentConversation.actor_user_id == user_id,
                AgentConversation.source_session_id == session_id,
                AgentConversation.college_id == college_id,
                AgentConversation.semester_id == semester_id,
                AgentConversation.environment == self.environment,
                AgentConversation.app_key_id == self.app_key_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("会话不在当前登录工作区")
        actor = self.runs._actor(user_id, session_id, touch_session=False)
        if row.scope_hash != self._scope_hash(actor, college_id, semester_id):
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "授权上下文已变化，请重新开始会话")
        if row.expires_at <= utcnow():
            raise ConflictError(message="会话已过期，请重新开始")
        return row

    def _retire(self, run_id):
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is not None:
            # Queued reads may continue under their live source session after cloud tools expire.
            run.credential_expires_at = utcnow()

    def _expire(self, conversation):
        turns = self.db.scalars(
            select(AgentTurn)
            .where(
                AgentTurn.conversation_id == conversation.id,
                AgentTurn.state.in_(["QUEUED", "SENDING"]),
                AgentTurn.deadline_at <= utcnow(),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        for turn in turns:
            queued = turn.state == "QUEUED"
            turn.state = "FAILED" if queued else "UNCERTAIN"
            turn.error_code = "CHAT_QUEUE_EXPIRED" if queued else "CHAT_WAIT_EXPIRED"
            turn.attempt_token = None
            self._retire(turn.run_id)
            if not queued:
                conversation.state = "UNCERTAIN"
        if turns:
            self.changed = True
            self.db.commit()

    @atomic_write
    def enqueue(self, conversation_id, user_id, session_id, **arguments):
        from app.modules.agent.chat_queue import enqueue

        return enqueue(self, conversation_id, user_id, session_id, **arguments)

    @atomic_write
    def claim_queued(self):
        from app.modules.agent.chat_queue import claim_queued

        return claim_queued(self)

    def _receipt(self, claim):
        row = self.db.scalar(
            select(AgentConversation)
            .where(
                AgentConversation.id == claim.conversation_id,
                AgentConversation.environment == self.environment,
                AgentConversation.app_key_id == self.app_key_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        turn = self.db.scalar(
            select(AgentTurn)
            .where(
                AgentTurn.id == claim.turn_id,
                AgentTurn.conversation_id == claim.conversation_id,
                AgentTurn.run_id == claim.run_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or turn is None
            or turn.state != "SENDING"
            or turn.attempt_token != claim.attempt_token
        ):
            return None
        if turn.deadline_at <= utcnow():
            self._expire(row)
            return None
        return row, turn

    @atomic_write
    def complete(self, claim, reply):
        pair = self._receipt(claim)
        if pair is None:
            return False
        row, turn = pair
        try:
            self._authorized(
                row.id,
                row.actor_user_id,
                row.source_session_id,
                college_id=row.college_id,
                semester_id=row.semester_id,
            )
        except AppError:
            row.state, turn.state, turn.error_code = "CLOSED", "FAILED", "CONTEXT_CHANGED"
            turn.attempt_token = None
            self._retire(turn.run_id)
            self.db.commit()
            return False
        if not isinstance(reply, str) or len(reply.encode()) > 128 * 1024:
            raise AppError(ErrorCode.VALIDATION_ERROR, "回复内容不合法", 422)
        turn.reply = reply.replace(claim.run_token, "[REDACTED]") if claim.run_token else reply
        turn.state, turn.attempt_token = "SUCCEEDED", None
        self._retire(turn.run_id)
        self.db.commit()
        return True

    @atomic_write
    def fail(self, claim, code, *, ambiguous):
        pair = self._receipt(claim)
        if pair is None:
            return False
        row, turn = pair
        turn.state = "UNCERTAIN" if ambiguous else "FAILED"
        turn.error_code = "CHAT_UPSTREAM_UNCERTAIN" if ambiguous else "CHAT_FAILED"
        turn.attempt_token = None
        if ambiguous:
            row.state = "UNCERTAIN"
        self._retire(turn.run_id)
        self.db.commit()
        return True

    def read(
        self, conversation_id, user_id, session_id, *, college_id, semester_id, before_turn_id=None
    ):
        row = self._authorized(
            conversation_id, user_id, session_id, college_id=college_id, semester_id=semester_id
        )
        self._expire(row)
        query = select(AgentTurn).where(AgentTurn.conversation_id == row.id)
        if before_turn_id is not None:
            if not isinstance(before_turn_id, int) or not 0 < before_turn_id < 2**63:
                raise AppError(ErrorCode.VALIDATION_ERROR, "历史游标不合法", 422)
            query = query.where(AgentTurn.id < before_turn_id)
        turns = list(
            self.db.scalars(
                query.order_by(AgentTurn.id.desc())
                .limit(21)
                .execution_options(populate_existing=True)
            )
        )
        more = len(turns) > 20
        turns = turns[:20]
        actions = {turn.run_id: [] for turn in turns}
        if actions:
            tasks = self.db.execute(
                select(AgentTask, AgentJob.tool_name)
                .join(AgentJob, AgentJob.task_id == AgentTask.id)
                .where(
                    AgentTask.run_id.in_(actions),
                    AgentTask.actor_user_id == row.actor_user_id,
                    AgentTask.source_session_id == row.source_session_id,
                    AgentJob.tool_name.in_(PAGES),
                )
                .order_by(AgentTask.id)
                .execution_options(populate_existing=True)
            )
            for task, tool_name in tasks:
                actions[task.run_id].append(task_handoff(task, tool_name))
        return {
            "id": str(row.id),
            "state": row.state,
            "college_id": str(row.college_id),
            "semester_id": str(row.semester_id),
            "next_before_turn_id": str(turns[-1].id) if more else None,
            "turns": [
                {
                    "id": str(turn.id),
                    "state": turn.state,
                    "user_text": turn.user_text,
                    "reply": turn.reply,
                    "error_code": turn.error_code,
                    "created_at": iso_utc(turn.created_at),
                    "actions": actions[turn.run_id],
                }
                for turn in reversed(turns)
            ],
        }
