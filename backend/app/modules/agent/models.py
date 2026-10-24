from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AgentRun(TimestampMixin, Base):
    """Identity association, not a copy of the user's permissions."""

    __tablename__ = "agent_run"
    __table_args__ = (
        Index("ix_agent_run_actor_created", "actor_user_id", "created_at"),
        UniqueConstraint("auto_change_execution_id", name="uq_agent_run_change_execution"),
        UniqueConstraint("objection_precheck_job_id", name="uq_agent_run_objection_job"),
        CheckConstraint(
            "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
            "AND workflow_kind IS NOT NULL AND workflow_kind = 'change' "
            "AND auto_change_execution_id IS NOT NULL AND objection_precheck_job_id IS NULL "
            "AND objection_precheck_attempt_digest IS NULL) OR "
            "(entry_kind = 'AUTOMATION' AND source_session_id IS NULL "
            "AND workflow_kind IS NOT NULL AND workflow_kind = 'objection' "
            "AND auto_change_execution_id IS NULL AND objection_precheck_job_id IS NOT NULL "
            "AND objection_precheck_attempt_digest IS NOT NULL) OR "
            "(entry_kind IN ('MANAGEMENT', 'SELF_SERVICE') AND source_session_id IS NOT NULL "
            "AND workflow_kind IS NULL AND auto_change_execution_id IS NULL "
            "AND objection_precheck_job_id IS NULL AND objection_precheck_attempt_digest IS NULL)",
            name=conv("ck_agent_run_identity_source"),
        ),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    app_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    source_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth_session.id", ondelete="RESTRICT")
    )
    workflow_kind: Mapped[str | None] = mapped_column(String(24))
    auto_change_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "auto_change_execution.id", ondelete="RESTRICT", name="fk_agent_run_change_execution"
        )
    )
    objection_precheck_job_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "objection_precheck_job.id", ondelete="RESTRICT", name="fk_agent_run_objection_job"
        )
    )
    objection_precheck_attempt_digest: Mapped[str | None] = mapped_column(String(64))
    college_id: Mapped[int | None] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    semester_id: Mapped[int | None] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    credential_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    credential_expires_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)


class AgentTask(TimestampMixin, Base):
    __tablename__ = "agent_task"
    __table_args__ = (
        UniqueConstraint(
            "actor_user_id", "source_session_id", "request_key", name="uq_agent_task_request"
        ),
        Index("ix_agent_task_actor_created", "actor_user_id", "created_at"),
        Index("ix_agent_task_run_status", "run_id", "status"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_run.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    source_session_id: Mapped[int] = mapped_column(
        ForeignKey("auth_session.id", ondelete="RESTRICT")
    )
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")


class AgentJob(TimestampMixin, Base):
    __tablename__ = "agent_job"
    __table_args__ = (
        UniqueConstraint("task_id", "stage", name="uq_agent_job_task_stage"),
        Index("ix_agent_job_dispatch", "status", "available_at", "id"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_task.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="EXECUTE")
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    available_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME_3)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))


class AgentWorkflowRun(TimestampMixin, Base):
    """Durable association with one cloud workflow; no credentials or model payloads."""

    __tablename__ = "agent_workflow_run"
    __table_args__ = (
        UniqueConstraint("app_id", "domain", "remote_run_id", name="uq_agent_workflow_remote"),
        Index("ix_agent_workflow_poll", "state", "next_poll_at"),
        MYSQL_TABLE_ARGS,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_run.id", ondelete="RESTRICT"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(String(32))
    domain: Mapped[int] = mapped_column(Integer)
    region: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="STARTING")
    outcome: Mapped[str | None] = mapped_column(String(24))
    remote_run_id: Mapped[str | None] = mapped_column(String(128))
    remote_status: Mapped[str | None] = mapped_column(String(24))
    request_id: Mapped[str | None] = mapped_column(String(128))
    attempt_token: Mapped[str] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME_3)
    next_poll_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    deadline_at: Mapped[datetime] = mapped_column(DATETIME_3)
    create_attempts: Mapped[int] = mapped_column(Integer, default=1)
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
