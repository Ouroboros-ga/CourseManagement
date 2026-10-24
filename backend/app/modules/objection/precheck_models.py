"""AI预审独立记录，不复用历史初核字段或终审状态。"""

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from app.core.database import Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class ObjectionPrecheckPolicy(TimestampMixin, Base):
    __tablename__ = "objection_precheck_policy"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    id: Mapped[int] = pk_column()
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), unique=True
    )
    authorizer_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ObjectionPrecheckJob(TimestampMixin, Base):
    __tablename__ = "objection_precheck_job"
    __table_args__ = (
        UniqueConstraint(
            "objection_id",
            "source_digest",
            "policy_version",
            "environment",
            "attempt_no",
            name="uq_objection_precheck_source",
        ),
        UniqueConstraint("retry_of_job_id", name="uq_precheck_retry_parent"),
        CheckConstraint("attempt_no >= 1", name=conv("ck_objection_precheck_attempt")),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_objection_precheck_status",
        ),
        MYSQL_TABLE_ARGS,
    )
    id: Mapped[int] = pk_column()
    objection_id: Mapped[int] = mapped_column(
        ForeignKey("objection.id", ondelete="CASCADE"), index=True
    )
    college_id: Mapped[int | None] = mapped_column(ForeignKey("college.id", ondelete="RESTRICT"))
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("objection_precheck_policy.id", ondelete="RESTRICT")
    )
    policy_version: Mapped[int] = mapped_column(Integer, default=0)
    authorizer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    initiated_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    environment: Mapped[str] = mapped_column(String(32))
    source_digest: Mapped[str] = mapped_column(String(64))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    retry_of_job_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "objection_precheck_job.id", ondelete="SET NULL", name="fk_precheck_retry_parent"
        )
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
