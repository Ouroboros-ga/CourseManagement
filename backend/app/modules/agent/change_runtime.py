"""Only policy-bound change workflows can reach the reassignment transaction."""

import secrets

from sqlalchemy import select

from app.core.database import utcnow
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.agent.models import AgentRun
from app.modules.agent.run_context import RunContext
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.inspection.auto_change_service import AutoChangeService
from app.modules.inspection.automation_models import AutoChangeExecution, AutoChangePolicy


def service_for_execution(db, execution_id):
    policy = db.scalar(
        select(AutoChangePolicy)
        .join(AutoChangeExecution, AutoChangeExecution.policy_id == AutoChangePolicy.id)
        .where(AutoChangeExecution.id == execution_id)
    )
    if policy is None:
        raise NotFoundError("后台换班来源不存在")
    return AutoChangeService(db, policy.college_id, policy.group_id, policy.semester_id), policy


def change_context(db, run):
    if (
        run.workflow_kind != "change"
        or run.auto_change_execution_id is None
        or run.source_session_id is not None
    ):
        raise PermissionDeniedError("后台运行来源无效")
    service, _ = service_for_execution(db, run.auto_change_execution_id)
    _, _, execution = service._locked(run.auto_change_execution_id)
    if execution.environment != run.environment:
        raise PermissionDeniedError("运行与源申请的环境不一致")
    request, _, _ = service._source(execution.request_id)
    if (
        run.actor_user_id != request.request_user_id
        or run.college_id != service.cid
        or run.semester_id != service.sid
    ):
        raise PermissionDeniedError("后台运行与源申请不一致")
    user = db.scalar(
        select(UserAccount)
        .where(UserAccount.id == request.request_user_id)
        .execution_options(populate_existing=True)
    )
    if user is None or user.status != "ACTIVE":
        raise PermissionDeniedError("换班申请人已停用")
    repo = IdentityRepository(db)
    actor = CurrentUser(
        user.id,
        user.username,
        user.display_name,
        user.status,
        repo.list_effective_role_codes(user.id),
        repo.list_effective_permissions(user.id),
    )
    return RunContext(
        str(run.id),
        "AUTOMATION",
        actor,
        service.cid,
        service.sid,
        "change",
        execution.id,
        run.credential_digest,
    )


def invoke_change(db, context, name):
    if (
        context.workflow_kind != "change"
        or context.auto_change_execution_id is None
        or context.credential_digest is None
    ):
        raise PermissionDeniedError("缺少绑定的后台执行来源")
    service, _ = service_for_execution(db, context.auto_change_execution_id)
    # Domain locks precede the run lock, matching issuance and credential renewal.
    service._locked(context.auto_change_execution_id)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == int(context.run_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        run is None
        or run.entry_kind != "AUTOMATION"
        or run.status != "ACTIVE"
        or run.revoked_at is not None
        or run.credential_expires_at <= utcnow()
        or run.auto_change_execution_id != context.auto_change_execution_id
        or run.actor_user_id != context.actor.id
        or run.college_id != context.college_id
        or run.semester_id != context.semester_id
        or run.workflow_kind != context.workflow_kind
        or not secrets.compare_digest(run.credential_digest, context.credential_digest)
    ):
        raise PermissionDeniedError("后台运行已失效或执行范围不一致")
    change_context(db, run)
    return (
        service.prepare(context.auto_change_execution_id)
        if name == "change_prepare"
        else (service.apply(context.auto_change_execution_id))
    )
