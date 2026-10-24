"""One durable workspace is also its bounded inspection queue item."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AgentImportWorkspace(TimestampMixin, Base):
    __tablename__ = "agent_import_workspace"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_agent_import_run"),
        UniqueConstraint("file_id", name="uq_agent_import_file"),
        UniqueConstraint("source_session_id", "request_key", name="uq_agent_import_request"),
        Index("ix_agent_import_queue", "state", "id"),
        Index("ix_agent_import_owner_expiry", "actor_user_id", "expires_at"),
        CheckConstraint(
            "state IN ('QUEUED','PROCESSING','READY','FAILED','CANCELED')", name="state"
        ),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="attempts"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_run.id", ondelete="RESTRICT"))
    file_id: Mapped[int] = mapped_column(ForeignKey("file_object.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    source_session_id: Mapped[int] = mapped_column(
        ForeignKey("auth_session.id", ondelete="RESTRICT")
    )
    request_key: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    scope_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="QUEUED")
    inspection_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME_3)
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3)
