"""Stored-source groups prepare original draft batches and their receipt atomically."""

import hashlib
from copy import deepcopy
from typing import Annotated

from pydantic import Field, model_validator
from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, PermissionDeniedError
from app.modules.agent.import_inspection import InspectionManifest, Target
from app.modules.agent.import_workspace_models import AgentImportWorkspace
from app.modules.agent.models import AgentRun
from app.modules.agent.schemas import Id, ToolArguments
from app.modules.agent.task_service import digest
from app.modules.importer.scoped_service import ScopedImporterService
from app.modules.importer.zip_preview import expand_zip


class PreviewIntent(ToolArguments):
    target: Target
    member_nos: list[Annotated[int, Field(strict=True, ge=1, le=1000)]] = Field(
        min_length=1, max_length=100
    )
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    teaching_class_id: Id | None = None
    course_type_id: Id | None = None

    @model_validator(mode="after")
    def normalize(self):
        if len(set(self.member_nos)) != len(self.member_nos):
            raise ValueError("Choose distinct members")
        self.member_nos.sort()
        self.request_key = self.request_key.lower()
        return self


def update_receipt(row, **changes):
    ledger = deepcopy(row.preview_json or {})
    current = {**ledger["current"], **changes}
    ledger["current"] = current
    ledger["receipts"] = [
        current if item["request_key"] == current["request_key"] else item
        for item in ledger.get("receipts", [])
    ]
    row.preview_json = ledger


def target_scope(service, context, intent):
    importer = ScopedImporterService(service.db, context.actor, context.college_id)
    importer._require_composite(context.actor.id, intent.target)
    spec = importer.get_template(context.actor, intent.target)
    semester = context.semester_id if "semester_id" in spec.scope_fields else None
    teaching = int(intent.teaching_class_id) if intent.teaching_class_id else None
    if teaching is not None:
        row = importer._academic.get_teaching_class(teaching)
        if row is None or row.semester_id != context.semester_id:
            raise NotFoundError("教学班不在当前资料学期")
    importer._validate_scope(intent.target, semester_id=semester, teaching_class_id=teaching)
    return importer, {
        "semester_id": semester,
        "teaching_class_id": teaching,
        "course_type_id": int(intent.course_type_id) if intent.course_type_id else None,
    }


def prepare(service, wid, *, user_id, session_id, college_id, semester_id, **arguments):
    intent = PreviewIntent.model_validate(arguments)
    row, file = service._authorized(wid, user_id, session_id, college_id, semester_id, lock=True)
    target_scope(service, service.runs.restore(row.run_id), intent)
    signature = digest(intent.model_dump(mode="json", exclude={"request_key"}))
    ledger = deepcopy(row.preview_json or {"receipts": []})
    for previous in ledger["receipts"]:
        if previous["request_key"] == intent.request_key:
            if previous["input_hash"] != signature:
                raise ConflictError(
                    ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求标识的资料选择已变化"
                )
            result = service._view(row, file, college_id, semester_id)
            result["preview"] = previous
            return result
    if row.state != "READY" or row.inspection_json is None:
        raise ConflictError(message="资料尚未整理完成或另一组正在处理，请先刷新")
    manifest = InspectionManifest.model_validate(row.inspection_json)
    members = {item.member_no: item for item in manifest.files}
    if any(no not in members or members[no].blocked for no in intent.member_nos):
        raise PermissionDeniedError("所选资料不可生成预览，请先处理问题")
    if any(members[no].target not in {None, intent.target} for no in intent.member_nos):
        raise PermissionDeniedError("已识别资料必须使用对应类型，不能改用另一类解析器")
    if len(ledger["receipts"]) >= 100:
        raise ConflictError(message="本工作区已达预览请求上限，请重新添加资料")
    current = {
        **intent.model_dump(mode="json"),
        "input_hash": signature,
        "status": "QUEUED",
        "batch_ids": [],
        "error_code": None,
    }
    row.preview_json = {"current": current, "receipts": [*ledger["receipts"], current]}
    row.state, row.attempt_count = "PREVIEW_QUEUED", 0
    result = service._view(row, file, college_id, semester_id)
    service.db.commit()
    return result


def locked_claim(service, claim):
    row = service.db.scalar(
        select(AgentImportWorkspace)
        .where(AgentImportWorkspace.id == claim.workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.state != "PREVIEW_PROCESSING"
        or row.attempt_token != claim.attempt_token
        or row.lease_until is None
        or row.lease_until <= utcnow()
    ):
        service.db.rollback()
        return None
    return row


def execute(service, claim, content):
    row = locked_claim(service, claim)
    if row is None:
        return False
    run = service.db.get(AgentRun, row.run_id)
    _, file = service._authorized(
        row.id, row.actor_user_id, row.source_session_id, run.college_id, run.semester_id
    )
    intent = PreviewIntent.model_validate(
        {name: claim.preview_request[name] for name in PreviewIntent.model_fields}
    )
    context = service.runs.restore(row.run_id)
    importer, options = target_scope(service, context, intent)
    manifest = InspectionManifest.model_validate(row.inspection_json)
    selected = [item for item in manifest.files if item.member_no in intent.member_nos]
    # Release the claim read lock before parsing. Cancellation can then fence the
    # claim while this bounded child prepares drafts, without waiting for its work.
    service.db.commit()
    names = [item.filename for item in selected]
    expanded = (
        dict(expand_zip(content, allow_template_notes=True, selected_names=names))
        if file.original_name.lower().endswith(".zip")
        else {file.original_name: content}
    )
    ids = []
    with importer.draft_source_snapshot():
        for item in selected:
            data = expanded[item.filename]
            if hashlib.sha256(data).hexdigest() != item.sha256:
                raise ConflictError(message="资料来源已变化")
            draft = importer.create_preview(
                context.actor,
                target=intent.target,
                content=data,
                filename=item.filename,
                replace=False,
                request_id=None,
                commit=False,
                **options,
            )
            batch = importer._repo.get_for_update(int(draft.id))
            batch.payload_json = {
                **batch.payload_json,
                "agent_workspace_id": str(row.id),
                "agent_member_no": item.member_no,
                "agent_group_key": intent.request_key,
            }
            ids.append(str(batch.id))
    row = locked_claim(service, claim)
    if row is None:
        return False
    update_receipt(row, status="SUCCEEDED", batch_ids=ids, error_code=None)
    row.state, row.attempt_token, row.lease_until = "READY", None, None
    service.db.commit()
    return True


def fail(service, claim, code):
    row = locked_claim(service, claim)
    if row is None:
        return False
    update_receipt(
        row,
        status="FAILED",
        batch_ids=[],
        error_code=code
        if code in {"CONTEXT_CHANGED", "SOURCE_CHANGED"}
        else "IMPORT_PREVIEW_FAILED",
    )
    row.state = "FAILED" if code in {"CONTEXT_CHANGED", "SOURCE_CHANGED"} else "READY"
    row.attempt_token, row.lease_until = None, None
    service.db.commit()
    return True
