"""Private interactive context and durable send attempts; credentials remain in AgentRun digests."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AgentConversation(TimestampMixin, Base):
    __tablename__ = "agent_conversation"
    __table_args__ = (
        UniqueConstraint("remote_conversation_id", name="uq_agent_conversation_remote"),
        Index("ix_agent_conversation_owner", "actor_user_id", "source_session_id", "created_at"),
        Index("ix_agent_conversation_pool", "environment", "app_key_id", "id"),
        CheckConstraint("state IN ('OPEN','UNCERTAIN','CLOSED')", name="state"),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="RESTRICT"))
    source_session_id: Mapped[int] = mapped_column(
        ForeignKey("auth_session.id", ondelete="RESTRICT")
    )
    college_id: Mapped[int] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id", ondelete="RESTRICT"))
    environment: Mapped[str] = mapped_column(String(32))
    app_key_id: Mapped[str] = mapped_column(String(64))
    remote_conversation_id: Mapped[str] = mapped_column(String(32))
    scope_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="OPEN")
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3)


class AgentTurn(TimestampMixin, Base):
    __tablename__ = "agent_turn"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_key", name="uq_agent_turn_request"),
        UniqueConstraint("run_id", name="uq_agent_turn_run"),
        UniqueConstraint("remote_request_id", name="uq_agent_turn_remote_request"),
        Index("ix_agent_turn_conversation", "conversation_id", "id"),
        Index("ix_agent_turn_queue", "state", "id"),
        CheckConstraint(
            "state IN ('QUEUED','SENDING','SUCCEEDED','FAILED','UNCERTAIN')", name="state"
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversation.id", ondelete="RESTRICT")
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_run.id", ondelete="RESTRICT"))
    request_key: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    remote_request_id: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="SENDING")
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DATETIME_3)
    user_text: Mapped[str] = mapped_column(Text)
    reply: Mapped[str | None] = mapped_column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"))
    error_code: Mapped[str | None] = mapped_column(String(64))
