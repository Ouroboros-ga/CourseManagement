"""Owned source admission and inspection receipts; business imports stay in the importer."""

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select

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
from app.modules.agent.import_inspection import InspectionError, InspectionManifest, validate_source
from app.modules.agent.import_workspace_models import AgentImportWorkspace
from app.modules.agent.models import AgentRun
from app.modules.agent.run_context import RunContext, RunService
from app.modules.agent.task_service import digest, visibility_hash
from app.modules.file.models import FileObject
from app.modules.file.service import FileService
from app.modules.file.storage import PRIVATE_IMPORT_PREFIX, build_default_storage
from app.modules.identity.models import UserAccount
from app.modules.organization.models import College
from app.modules.organization.service import atomic_write

logger = logging.getLogger(__name__)
MIMES = {
    ".zip": "application/zip",
    ".csv": "text/csv",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class ImportClaim:
    workspace_id: int
    attempt_token: str = field(repr=False)
    object_key: str = field(repr=False)
    filename: str = field(repr=False)
    sha256: str = field(repr=False)
    size_bytes: int
    can_inspect: bool = True
    stage: str = "INSPECT"
    preview_request: dict | None = field(default=None, repr=False)


class ImportWorkspaceService:
    def __init__(self, db, connections, *, environment, app_key_id, storage=None):
        self.db, self.environment, self.app_key_id = db, environment, app_key_id
        self.runs = RunService(db, connections, environment=environment)
        self.storage = storage if storage is not None else build_default_storage(get_settings())
        self.changed = False

    def _scope(self, context):
        settings = get_settings()
        if not settings.agent_tools_enabled or not settings.agent_import_workspace_enabled:
            raise NotFoundError("资料助手暂未开放")
        if (
            context.entry_kind != "MANAGEMENT"
            or context.college_id is None
            or context.semester_id is None
        ):
            raise PermissionDeniedError()
        current = visibility_hash(self.db, context, "import_preview_review")
        semester = self.db.get(Semester, context.semester_id, populate_existing=True)
        college = self.db.get(College, context.college_id, populate_existing=True)
        if semester is None or college is None:
            raise NotFoundError()
        if semester.status != "ACTIVE":
            raise ConflictError(message="学期已归档，请切换有效学期后再添加资料")
        return digest(
            {
                "visibility": current,
                "semester": semester.id,
                "status": semester.status,
                "configuration": college.configuration_revision,
            }
        )

    def _preflight(self, user_id, session_id, college_id, semester_id):
        connection = self.runs._connection(self.app_key_id)
        if connection.entry_kind != "MANAGEMENT":
            raise PermissionDeniedError()
        actor = self.runs._actor(user_id, session_id, touch_session=False)
        return self._scope(RunContext("0", "MANAGEMENT", actor, college_id, semester_id))

    def _authorized(
        self, workspace_id, user_id, session_id, college_id, semester_id, *, lock=False
    ):
        query = (
            select(AgentImportWorkspace)
            .join(AgentRun, AgentRun.id == AgentImportWorkspace.run_id)
            .where(
                AgentImportWorkspace.id == workspace_id,
                AgentImportWorkspace.actor_user_id == user_id,
                AgentImportWorkspace.source_session_id == session_id,
                AgentRun.environment == self.environment,
                AgentRun.app_key_id == self.app_key_id,
                AgentRun.actor_user_id == user_id,
                AgentRun.source_session_id == session_id,
                AgentRun.college_id == college_id,
                AgentRun.semester_id == semester_id,
            )
        )
        if lock:
            query = query.with_for_update()
        row = self.db.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError("资料不在当前登录工作区")
        context = self.runs.restore(row.run_id)
        if row.scope_hash != self._scope(context):
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "授权上下文已变化，请重新添加资料")
        if row.expires_at <= utcnow():
            raise AppError(ErrorCode.VERSION_CONFLICT, "资料工作区已过期，请重新添加资料", 410)
        file = self.db.get(FileObject, row.file_id, populate_existing=True)
        if (
            file is None
            or file.status != "READY"
            or file.uploader_user_id != user_id
            or file.category != "IMPORT_FILE"
            or not file.object_key.startswith(PRIVATE_IMPORT_PREFIX)
            or file.expires_at is None
            or file.expires_at <= utcnow()
        ):
            raise NotFoundError("原始资料已不可用")
        current_input = digest(
            {
                "college": college_id,
                "semester": semester_id,
                "filename": file.original_name,
                "sha256": file.sha256,
            }
        )
        if current_input != row.input_hash:
            raise NotFoundError("原始资料信息已变化，请重新添加")
        return row, file

    def _view(self, row, file, college_id, semester_id):
        return {
            "workspace_id": str(row.id),
            "state": row.state,
            "filename": file.original_name,
            "college_id": str(college_id),
            "semester_id": str(semester_id),
            "inspection": row.inspection_json
            if row.state in {"READY", "PREVIEW_QUEUED", "PREVIEW_PROCESSING"}
            else None,
            "preview": (row.preview_json or {}).get("current"),
            "preview_receipts": (row.preview_json or {}).get("receipts", []),
            "error_code": row.error_code,
            "created_at": iso_utc(row.created_at),
            "expires_at": iso_utc(row.expires_at),
            "business_data_applied": False,
        }

    def _existing(self, user_id, session_id, key):
        return self.db.scalar(
            select(AgentImportWorkspace)
            .where(
                AgentImportWorkspace.actor_user_id == user_id,
                AgentImportWorkspace.source_session_id == session_id,
                AgentImportWorkspace.request_key == key,
            )
            .execution_options(populate_existing=True)
        )

    def _replay(self, row, input_hash, scope):
        if row.input_hash != input_hash:
            raise ConflictError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求标识的资料已变化")
        return self.read(row.id, **scope)

    @atomic_write
    def upload(
        self,
        *,
        user_id,
        session_id,
        college_id,
        semester_id,
        content,
        filename,
        request_key,
        request_id=None,
    ):
        try:
            fingerprint = validate_source(content, filename)
        except InspectionError:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "请添加符合大小要求的ZIP或Excel/CSV资料", 422
            ) from None
        if not isinstance(request_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", request_key
        ):
            raise AppError(ErrorCode.VALIDATION_ERROR, "资料请求标识不合法", 422)
        request_key = request_key.lower()
        scope = dict(
            user_id=user_id, session_id=session_id, college_id=college_id, semester_id=semester_id
        )
        input_hash = digest(
            {
                "college": college_id,
                "semester": semester_id,
                "filename": filename,
                "sha256": fingerprint,
            }
        )
        self._preflight(user_id, session_id, college_id, semester_id)
        existing = self._existing(user_id, session_id, request_key)
        if existing:
            return self._replay(existing, input_hash, scope)
        self.db.rollback()  # No transaction is held while the storage backend performs I/O.
        suffix = Path(filename).suffix.lower()
        key = f"{PRIVATE_IMPORT_PREFIX}{secrets.token_hex(24)}{suffix}"
        commit_started = False
        try:
            self.storage.save(key, content, MIMES[suffix])
            self.db.scalar(select(UserAccount).where(UserAccount.id == user_id).with_for_update())
            scope_hash = self._preflight(user_id, session_id, college_id, semester_id)
            existing = self._existing(user_id, session_id, request_key)
            if existing:
                result = self._replay(existing, input_hash, scope)
                self.db.rollback()
                return result
            count = self.db.scalar(
                select(func.count())
                .select_from(AgentImportWorkspace)
                .where(
                    AgentImportWorkspace.actor_user_id == user_id,
                    AgentImportWorkspace.expires_at > utcnow(),
                )
            )
            if count >= 20:
                raise AppError(ErrorCode.RATE_LIMITED, "当前资料工作区已达20份，请稍后再添加", 429)
            file_service = FileService(self.db, storage=self.storage)
            file = FileObject(
                object_key=key,
                category="IMPORT_FILE",
                original_name=filename,
                content_type=MIMES[suffix],
                size_bytes=len(content),
                sha256=fingerprint,
                uploader_user_id=user_id,
                status="READY",
                retention_policy_version=get_settings().file_retention_policy_version,
                expires_at=file_service._retention_deadline("IMPORT_FILE"),
            )
            self.db.add(file)
            self.db.flush()
            run, _discarded_token = self.runs.issue_in_transaction(
                self.app_key_id, user_id, session_id, college_id=college_id, semester_id=semester_id
            )
            run.credential_expires_at = utcnow()
            row = AgentImportWorkspace(
                run_id=run.id,
                file_id=file.id,
                actor_user_id=user_id,
                source_session_id=session_id,
                request_key=request_key,
                input_hash=input_hash,
                scope_hash=scope_hash,
                state="QUEUED",
                expires_at=utcnow() + timedelta(hours=24),
            )
            self.db.add(row)
            self.db.flush()
            file_service._audit(
                actor_user_id=user_id,
                action="agent.import.upload",
                resource_id=str(file.id),
                after={
                    "workspace_id": str(row.id),
                    "college_id": str(college_id),
                    "semester_id": str(semester_id),
                },
                request_id=request_id,
            )
            result = self._view(row, file, college_id, semester_id)
            commit_started = True
            self.db.commit()
            return result
        finally:
            if not commit_started:
                self.db.rollback()
                try:
                    self.storage.delete(key)
                except Exception:
                    logger.error("agent_import_unused_blob_cleanup_failed")

    def read(self, workspace_id, *, user_id, session_id, college_id, semester_id):
        row, file = self._authorized(workspace_id, user_id, session_id, college_id, semester_id)
        return self._view(row, file, college_id, semester_id)

    @atomic_write
    def prepare_previews(self, workspace_id, **arguments):
        from app.modules.agent.import_workspace_previews import prepare

        return prepare(self, workspace_id, **arguments)

    @atomic_write
    def execute_previews(self, claim, content):
        from app.modules.agent.import_workspace_previews import execute

        return execute(self, claim, content)

    @atomic_write
    def cancel(self, workspace_id, *, user_id, session_id, college_id, semester_id):
        row, _ = self._authorized(
            workspace_id, user_id, session_id, college_id, semester_id, lock=True
        )
        if row.state in {"QUEUED", "PROCESSING", "PREVIEW_QUEUED", "PREVIEW_PROCESSING"}:
            if row.state.startswith("PREVIEW_"):
                from app.modules.agent.import_workspace_previews import update_receipt

                update_receipt(row, status="CANCELED", batch_ids=[], error_code=None)
            row.state, row.attempt_token, row.lease_until = "CANCELED", None, None
        self.db.commit()

    @atomic_write
    def claim(self):
        now = utcnow()
        row = self.db.scalar(
            select(AgentImportWorkspace)
            .join(AgentRun, AgentRun.id == AgentImportWorkspace.run_id)
            .where(
                AgentRun.environment == self.environment,
                AgentRun.app_key_id == self.app_key_id,
                (AgentImportWorkspace.state.in_(["QUEUED", "PREVIEW_QUEUED"]))
                | (
                    (AgentImportWorkspace.state.in_(["PROCESSING", "PREVIEW_PROCESSING"]))
                    & (AgentImportWorkspace.lease_until <= now)
                ),
            )
            .order_by(AgentImportWorkspace.id)
            .with_for_update(skip_locked=True)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if row is None:
            self.db.rollback()
            return None
        try:
            run = self.db.get(AgentRun, row.run_id)
            _, file = self._authorized(
                row.id, row.actor_user_id, row.source_session_id, run.college_id, run.semester_id
            )
            if row.attempt_count >= 3:
                raise ConflictError(message="资料整理重试已达上限")
        except AppError:
            if row.state.startswith("PREVIEW_"):
                from app.modules.agent.import_workspace_previews import update_receipt

                update_receipt(
                    row,
                    status="FAILED",
                    batch_ids=[],
                    error_code="IMPORT_PREVIEW_FAILED"
                    if row.attempt_count >= 3
                    else "CONTEXT_CHANGED",
                )
            row.state = "FAILED"
            row.error_code = (
                "IMPORT_INSPECTION_FAILED" if row.attempt_count >= 3 else "CONTEXT_CHANGED"
            )
            row.inspection_json, row.attempt_token, row.lease_until = None, None, None
            self.db.commit()
            self.changed = True
            return None
        preview = row.state.startswith("PREVIEW_")
        row.state, row.attempt_token = (
            ("PREVIEW_PROCESSING" if preview else "PROCESSING"),
            secrets.token_urlsafe(32),
        )
        if preview:
            from app.modules.agent.import_workspace_previews import update_receipt

            update_receipt(row, status="RUNNING")
        row.attempt_count += 1
        row.lease_until = now + timedelta(seconds=120)
        claim = ImportClaim(
            row.id,
            row.attempt_token,
            file.object_key,
            file.original_name,
            file.sha256,
            file.size_bytes,
            stage="PREVIEW" if preview else "INSPECT",
            preview_request=(row.preview_json or {}).get("current") if preview else None,
        )
        self.db.commit()
        self.changed = True
        return claim

    @atomic_write
    def finish(self, claim, inspection, *, error_code=None):
        if claim.stage == "PREVIEW":
            from app.modules.agent.import_workspace_previews import fail

            return fail(self, claim, error_code or "IMPORT_PREVIEW_FAILED")
        row = self.db.scalar(
            select(AgentImportWorkspace)
            .where(AgentImportWorkspace.id == claim.workspace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or row.state != "PROCESSING"
            or row.attempt_token != claim.attempt_token
            or row.lease_until is None
            or row.lease_until <= utcnow()
        ):
            self.db.rollback()
            return False
        try:
            run = self.db.get(AgentRun, row.run_id)
            _, file = self._authorized(
                row.id, row.actor_user_id, row.source_session_id, run.college_id, run.semester_id
            )
            if (
                file.sha256 != claim.sha256
                or file.object_key != claim.object_key
                or file.size_bytes != claim.size_bytes
                or file.original_name != claim.filename
            ):
                error_code = "SOURCE_CHANGED"
        except AppError:
            error_code = "CONTEXT_CHANGED"
        row.inspection_json = None
        if error_code is None:
            try:
                parsed = InspectionManifest.model_validate(inspection)
                if parsed.source_sha256 != claim.sha256:
                    error_code = "SOURCE_CHANGED"
                else:
                    row.inspection_json = parsed.model_dump(mode="json")
            except ValidationError:
                error_code = "IMPORT_INSPECTION_FAILED"
        row.state = "READY" if error_code is None else "FAILED"
        row.error_code = (
            error_code
            if error_code
            in {
                None,
                "CONTEXT_CHANGED",
                "SOURCE_CHANGED",
                "IMPORT_INSPECTION_INVALID",
                "IMPORT_INSPECTION_TIMEOUT",
                "IMPORT_INSPECTION_FAILED",
                "IMPORT_INSPECTION_UNAVAILABLE",
            }
            else "IMPORT_INSPECTION_FAILED"
        )
        row.attempt_token, row.lease_until = None, None
        self.db.commit()
        return True
