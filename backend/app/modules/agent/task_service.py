import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from pydantic import ValidationError
from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.agent.models import AgentJob, AgentRun, AgentTask
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.run_context import RunContext, RunService
from app.modules.agent.schemas import AppConnection


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def visibility_hash(db: Session, context: RunContext, tool_name: str) -> str:
    """A digest of existing scope guards, never a second permission definition."""
    if tool_name == "system_probe":
        return digest({"actor": context.actor.id})
    if tool_name in {
        "report_attendance_summary",
        "report_attendance_export_prepare",
        "responsibility_tasks_list",
        "import_preview_review",
    }:
        from app.modules.identity.resource_scope import resolve_scope

        if context.college_id is None or not get_settings().campus_business_scoped_enabled:
            raise PermissionDeniedError()
        action = (
            "inspection.read" if tool_name == "responsibility_tasks_list" else "statistics.read"
        )
        if tool_name == "import_preview_review":
            action = "import.execute"
        scope = resolve_scope(
            db,
            context.actor,
            context.college_id,
            action,
            write=tool_name == "import_preview_review",
        )
        # College revision changes invalidate stored results even if access still exists.
        return digest(
            {
                "actor": context.actor.id,
                "college": scope.college_id,
                "revision": scope.authorization_revision,
                "constraints": repr(scope.constraints),
                "unrestricted": scope.unrestricted,
            }
        )
    from app.modules.timetable.repository import PersonalTimetableRepository

    student = PersonalTimetableRepository(db).student(context.actor.id)
    if tool_name == "self_attendance_list":
        from app.modules.attendance.service import AttendanceService

        AttendanceService(db)._require(context.actor.id, "attendance.read")
    return digest({"actor": context.actor.id, "student": student.id})


@dataclass(frozen=True)
class Claim:
    job_id: int
    task_id: int
    attempt_token: str
    tool_name: str
    arguments: dict
    run_id: int
    scope_hash: str


class TaskService:
    """Submit is flush-only so business events and jobs can commit together."""

    def __init__(self, db: Session, connections: list[AppConnection], *, environment: str):
        self.db = db
        self.runs = RunService(db, connections, environment=environment)

    def _task(self, task_id: int) -> AgentTask:
        task = self.db.get(AgentTask, task_id)
        if task is None:
            raise NotFoundError()
        return task

    def submit(self, run_id, user_id, session_id, tool_name, arguments, request_key):
        if not isinstance(request_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", request_key
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "请求标识长度需为1到64", 422)
        # Match MySQL's default case-insensitive key equality on SQLite as well.
        request_key = request_key.lower()
        run = self.db.get(AgentRun, run_id)
        if (
            run is None
            or run.entry_kind == "AUTOMATION"
            or run.actor_user_id != user_id
            or run.source_session_id != session_id
        ):
            raise NotFoundError()
        context = self.runs.restore(run_id)
        spec = next(
            (
                item
                for item in ToolRegistry().list_for(context.entry_kind)
                if item.name == tool_name
            ),
            None,
        )
        if spec is None:
            raise NotFoundError("工具不存在")
        if tool_name == "task_status_get":
            raise AppError(ErrorCode.VALIDATION_ERROR, "状态查询无需排队", 422)
        try:
            normalized = spec.input_model.model_validate(arguments).model_dump(mode="json")
        except ValidationError:
            raise AppError(ErrorCode.VALIDATION_ERROR, "工具参数不符合合同", 422) from None
        input_hash = digest(
            {"run": run_id, "tool": tool_name, "version": spec.version, "arguments": normalized}
        )
        existing_query = select(AgentTask).where(
            AgentTask.actor_user_id == user_id,
            AgentTask.source_session_id == session_id,
            AgentTask.request_key == request_key,
        )
        existing = self.db.scalar(existing_query)
        if existing:
            if existing.input_hash != input_hash:
                raise ConflictError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求标识的内容已变化")
            return existing
        # Serialize admission for this run without inventing a distributed capacity service.
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run.status != "ACTIVE" or run.revoked_at is not None:
            raise PermissionDeniedError("运行已关闭")
        concurrent = self.db.scalar(
            existing_query.with_for_update().execution_options(populate_existing=True)
        )
        if concurrent:
            if concurrent.input_hash != input_hash:
                raise ConflictError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "请求标识冲突")
            return concurrent
        pending = self.db.scalars(
            select(AgentTask.id)
            .where(
                AgentTask.run_id == run_id,
                AgentTask.status.in_(["QUEUED", "RUNNING"]),
            )
            .with_for_update()
        ).all()
        if len(pending) >= get_settings().agent_run_max_pending_tasks:
            raise AppError(ErrorCode.RATE_LIMITED, "本次运行待处理任务已达上限", 429)
        scope_hash = visibility_hash(self.db, context, tool_name)
        task = AgentTask(
            run_id=run_id,
            actor_user_id=user_id,
            source_session_id=session_id,
            request_key=request_key,
            input_hash=input_hash,
            scope_hash=scope_hash,
            status="QUEUED",
        )
        connection = self.db.connection()
        if (
            connection.dialect.name == "sqlite"
            and not connection.connection.driver_connection.in_transaction
        ):
            # sqlite3 legacy mode doesn't begin a transaction for SELECT/SAVEPOINT.
            # Explicit BEGIN prevents RELEASE SAVEPOINT from committing the parent unit.
            connection.exec_driver_sql("BEGIN")
        try:
            with self.db.begin_nested():
                self.db.add(task)
                self.db.flush()
                self.db.add(
                    AgentJob(
                        task_id=task.id,
                        stage="EXECUTE",
                        tool_name=tool_name,
                        arguments_json=normalized,
                        status="QUEUED",
                        available_at=utcnow(),
                    )
                )
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(existing_query)
            if existing is None or existing.input_hash != input_hash:
                raise ConflictError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "请求标识冲突") from None
            return existing
        return task

    def read(self, task_id, user_id, *, run_id=None):
        task = self.db.scalar(
            select(AgentTask)
            .where(AgentTask.id == task_id, AgentTask.actor_user_id == user_id)
            .execution_options(populate_existing=True)
        )
        if task is None or (run_id is not None and task.run_id != run_id):
            raise NotFoundError()
        job = self.db.scalar(
            select(AgentJob)
            .where(AgentJob.task_id == task.id)
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise NotFoundError()
        context = self.runs.restore(task.run_id)
        if visibility_hash(self.db, context, job.tool_name) != task.scope_hash:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "可见范围已变化，请重新查询")
        return {
            "task_id": str(task.id),
            "status": task.status,
            "stage": job.stage,
            "result": job.result_json if task.status == "SUCCEEDED" else None,
            "error_code": job.error_code,
        }

    def claim(self, worker_id: str) -> Claim | None:
        now = utcnow()
        # Abandoned last attempts become terminal instead of spinning forever.
        exhausted = self.db.scalars(
            select(AgentJob)
            .where(
                AgentJob.status == "RUNNING",
                AgentJob.lease_until <= now,
                AgentJob.attempt_count >= 3,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for abandoned in exhausted:
            abandoned.status, abandoned.error_code = "FAILED", "ATTEMPTS_EXHAUSTED"
            self._task(abandoned.task_id).status = "FAILED"
        job = self.db.scalar(
            select(AgentJob)
            .where(
                AgentJob.attempt_count < 3,
                or_(
                    and_(AgentJob.status == "QUEUED", AgentJob.available_at <= now),
                    and_(AgentJob.status == "RUNNING", AgentJob.lease_until <= now),
                ),
            )
            .order_by(AgentJob.available_at, AgentJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            self.db.commit()
            return None
        job.status = "RUNNING"
        job.attempt_count += 1
        job.attempt_token, job.lease_owner = secrets.token_hex(16), worker_id[:64]
        job.lease_until = now + timedelta(seconds=60)
        task = self._task(job.task_id)
        task.status = "RUNNING"
        claim = Claim(
            job.id,
            task.id,
            job.attempt_token,
            job.tool_name,
            dict(job.arguments_json),
            task.run_id,
            task.scope_hash,
        )
        self.db.commit()
        return claim

    def heartbeat(self, claim: Claim) -> bool:
        now = utcnow()
        updated = self.db.execute(
            update(AgentJob)
            .where(
                AgentJob.id == claim.job_id,
                AgentJob.status == "RUNNING",
                AgentJob.attempt_token == claim.attempt_token,
                AgentJob.lease_until > now,
            )
            .values(lease_until=now + timedelta(seconds=60))
        )
        self.db.commit()
        return cast(CursorResult, updated).rowcount == 1

    def finish(self, claim: Claim, result: dict | None, *, error_code=None, retry=False) -> bool:
        now = utcnow()
        job = self.db.scalar(
            select(AgentJob)
            .where(
                AgentJob.id == claim.job_id,
                AgentJob.attempt_token == claim.attempt_token,
                AgentJob.status == "RUNNING",
                AgentJob.lease_until > now,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            self.db.rollback()
            return False
        status = "SUCCEEDED" if error_code is None else "FAILED"
        if retry and job.attempt_count < 3:
            status = "QUEUED"
            job.available_at = now + timedelta(seconds=2**job.attempt_count)
        job.status, job.error_code, job.result_json = status, error_code, result
        job.lease_until, job.lease_owner = None, None
        self._task(job.task_id).status = status
        self.db.commit()
        return True

    def cancel(self, task_id, user_id):
        task = self.db.scalar(
            select(AgentTask).where(AgentTask.id == task_id, AgentTask.actor_user_id == user_id)
        )
        if task is None:
            raise NotFoundError()
        # Match the Worker lock order: job before task. No domain side effects in this stage.
        changed = self.db.execute(
            update(AgentJob)
            .where(AgentJob.task_id == task.id, AgentJob.status.in_(["QUEUED", "RUNNING"]))
            .values(status="CANCELED", lease_until=None)
        )
        if changed.rowcount:
            self.db.execute(
                update(AgentTask).where(AgentTask.id == task.id).values(status="CANCELED")
            )
        self.db.commit()
