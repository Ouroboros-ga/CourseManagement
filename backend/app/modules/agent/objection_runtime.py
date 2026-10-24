"""Only one policy-bound objection and one claimed attempt are reachable per run."""

import hashlib
import secrets

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.agent.models import AgentRun
from app.modules.agent.run_context import RunContext
from app.modules.agent.schemas import ObjectionMaterialQuery, ObjectionSaveQuery
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.precheck_service import ObjectionPrecheckService


def service_for_job(db, job_id):
    job = db.scalar(
        select(ObjectionPrecheckJob)
        .where(
            ObjectionPrecheckJob.id == job_id,
            ObjectionPrecheckJob.environment == get_settings().app_env,
        )
        .execution_options(populate_existing=True)
    )
    if job is None or job.college_id is None:
        raise NotFoundError("预审来源不存在或范围未明确")
    return ObjectionPrecheckService(db, job.college_id)


def objection_context(db, run):
    if (
        run.workflow_kind != "objection"
        or run.objection_precheck_job_id is None
        or run.source_session_id is not None
        or run.auto_change_execution_id is not None
        or run.objection_precheck_attempt_digest is None
    ):
        raise PermissionDeniedError("申诉预审运行来源无效")
    service = service_for_job(db, run.objection_precheck_job_id)
    job, row = service._execution(run.objection_precheck_job_id)
    completed = run.status == "COMPLETED"
    if completed:
        if job.status != "SUCCEEDED" or job.result_json is None:
            raise PermissionDeniedError("预审完成回执与领域结果不一致")
    else:
        service._assert_attempt(job, job.attempt_token)
    if (
        job.environment != run.environment
        or job.initiated_by_user_id != run.actor_user_id
        or job.college_id != run.college_id
        or row[2].semester_id != run.semester_id
        or (
            not completed
            and not secrets.compare_digest(
                run.objection_precheck_attempt_digest,
                hashlib.sha256(job.attempt_token.encode()).hexdigest(),
            )
        )
    ):
        raise PermissionDeniedError("申诉预审运行与当前来源或执行批次不一致")
    actor = service._actor(job.initiated_by_user_id)
    return RunContext(
        run_id=str(run.id),
        entry_kind="AUTOMATION",
        actor=actor,
        college_id=job.college_id,
        semester_id=row[2].semester_id,
        workflow_kind="objection",
        credential_digest=run.credential_digest,
        objection_precheck_job_id=job.id,
        objection_precheck_attempt_digest=run.objection_precheck_attempt_digest,
    )


def invoke_objection(db, context, name, query):
    if (
        context.workflow_kind != "objection"
        or context.objection_precheck_job_id is None
        or context.credential_digest is None
        or context.objection_precheck_attempt_digest is None
        or context.auto_change_execution_id is not None
    ):
        raise PermissionDeniedError("缺少绑定的申诉预审来源")
    service = service_for_job(db, context.objection_precheck_job_id)
    # Domain locks precede the run lock, matching trusted issuance and rotation.
    job, _ = service._execution(context.objection_precheck_job_id)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == int(context.run_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        run is None
        or run.entry_kind != "AUTOMATION"
        or run.status not in {"ACTIVE", "COMPLETED"}
        or run.revoked_at is not None
        or run.credential_expires_at <= utcnow()
        or run.workflow_kind != context.workflow_kind
        or run.objection_precheck_job_id != context.objection_precheck_job_id
        or run.objection_precheck_attempt_digest != context.objection_precheck_attempt_digest
        or run.actor_user_id != context.actor.id
        or run.college_id != context.college_id
        or run.semester_id != context.semester_id
        or not secrets.compare_digest(run.credential_digest, context.credential_digest)
    ):
        raise PermissionDeniedError("申诉预审运行已失效或来源不一致")
    objection_context(db, run)
    if run.status == "COMPLETED":
        if name != "objection_precheck_save":
            raise PermissionDeniedError("已完成预审仅允许核对原保存回执")
        assert isinstance(query, ObjectionSaveQuery)
        if query.result.model_dump() != job.result_json:
            raise ConflictError(message="预审已保存，不能覆盖原建议")
        current = service._current(
            job, service._source(job.objection_id, lock=True), lock_files=True
        )
        return _receipt(job.id, "SUCCEEDED" if current else "STALE")
    if name == "objection_case_get":
        return service.case_get(job.id, job.attempt_token)
    if name == "objection_material_access":
        assert isinstance(query, ObjectionMaterialQuery)
        return service.file_access(job.id, job.attempt_token, int(query.file_id)).model_dump(
            mode="json"
        )
    assert name == "objection_precheck_save" and isinstance(query, ObjectionSaveQuery)
    try:
        status = service.finish_in_transaction(job.id, job.attempt_token, query.result)
        run.status = "COMPLETED" if status == "SUCCEEDED" else "CLOSED"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _receipt(job.id, status)


def _receipt(job_id, status):
    return {
        "job_id": str(job_id),
        "precheck_status": status,
        "status": "SUCCEEDED" if status == "SUCCEEDED" else "MANUAL_REQUIRED",
    }
