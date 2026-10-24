import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.exceptions import NotFoundError, PermissionDeniedError, UnauthenticatedError
from app.modules.agent.models import AgentRun
from app.modules.agent.schemas import AppConnection as AppConnection
from app.modules.identity.service import CurrentUser, IdentityService
from app.modules.organization.service import atomic_write


@dataclass(frozen=True)
class RunContext:
    run_id: str
    entry_kind: str
    actor: CurrentUser
    college_id: int | None
    semester_id: int | None
    workflow_kind: str | None = None
    auto_change_execution_id: int | None = None
    credential_digest: str | None = None
    objection_precheck_job_id: int | None = None
    objection_precheck_attempt_digest: str | None = None


class RunService:
    def __init__(self, db: Session, connections: list[AppConnection], *, environment: str):
        self.db = db
        self.connections = connections
        self.environment = environment
        if len({c.app_key_id for c in connections}) != len(connections):
            raise ValueError("Duplicate app_key_id")
        if len({c.key_digest for c in connections}) != len(connections):
            raise ValueError("App keys must be independent")

    def _connection(self, app_key_id: str) -> AppConnection:
        for connection in self.connections:
            if connection.app_key_id == app_key_id and connection.environment == self.environment:
                return connection
        raise PermissionDeniedError("应用未启用")

    def _actor(self, user_id: int, session_id: int, *, touch_session: bool = True) -> CurrentUser:
        actor = IdentityService(self.db).resolve_session_user(
            user_id, session_id, touch_session=touch_session
        )
        if actor.pre_binding:
            raise PermissionDeniedError("请先完成身份绑定")
        return actor

    def issue(
        self,
        app_key_id: str,
        user_id: int,
        session_id: int,
        *,
        college_id: int | None = None,
        semester_id: int | None = None,
    ):
        return self._issue(
            app_key_id,
            user_id,
            session_id,
            college_id=college_id,
            semester_id=semester_id,
            commit=True,
        )

    @atomic_write
    def issue_in_transaction(
        self,
        app_key_id: str,
        user_id: int,
        session_id: int,
        *,
        college_id: int | None = None,
        semester_id: int | None = None,
    ):
        return self._issue(
            app_key_id,
            user_id,
            session_id,
            college_id=college_id,
            semester_id=semester_id,
            commit=False,
        )

    def _issue(
        self,
        app_key_id: str,
        user_id: int,
        session_id: int,
        *,
        college_id: int | None = None,
        semester_id: int | None = None,
        commit: bool,
    ):
        """Internal only; never expose raw credentials to a browser or model."""
        connection = self._connection(app_key_id)
        if connection.entry_kind == "AUTOMATION":
            raise PermissionDeniedError("后台运行必须绑定有效策略申请")
        actor = self._actor(user_id, session_id, touch_session=commit)
        if connection.entry_kind == "MANAGEMENT":
            if college_id is None:
                raise PermissionDeniedError("请选择有权访问的学院")
            from app.modules.organization.service import CampusService

            capabilities = CampusService(self.db).capabilities(actor, college_id)
            if not capabilities["capabilities"]:
                raise PermissionDeniedError("没有学院工作区权限")
        elif college_id is not None:
            raise PermissionDeniedError("本人助手不接受学院管理范围")
        token = secrets.token_urlsafe(32)
        run = AgentRun(
            app_key_id=app_key_id,
            entry_kind=connection.entry_kind,
            environment=self.environment,
            actor_user_id=user_id,
            source_session_id=session_id,
            college_id=college_id,
            semester_id=semester_id,
            credential_digest=self._digest(token),
            credential_expires_at=utcnow() + timedelta(minutes=10),
            status="ACTIVE",
        )
        self.db.add(run)
        self.db.flush()
        if commit:
            self.db.commit()
        return run, token

    @atomic_write
    def issue_change(self, app_key_id: str, execution_id: int):
        """Trusted dispatcher only; flush-only to share the dispatch transaction."""
        from app.modules.agent.change_runtime import service_for_execution

        connection = self._connection(app_key_id)
        if connection.entry_kind != "AUTOMATION" or connection.workflow_kind != "change":
            raise PermissionDeniedError("该应用不是换班工作流")
        service, _ = service_for_execution(self.db, execution_id)
        _, _, execution = service._locked(execution_id)
        if execution.environment != self.environment:
            raise PermissionDeniedError("源申请不属于当前运行环境")
        request, _, _ = service._source(execution.request_id)
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.auto_change_execution_id == execution_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        token = secrets.token_urlsafe(32)
        if run is None:
            run = AgentRun(
                app_key_id=app_key_id,
                entry_kind="AUTOMATION",
                workflow_kind="change",
                environment=self.environment,
                actor_user_id=request.request_user_id,
                source_session_id=None,
                college_id=service.cid,
                semester_id=service.sid,
                auto_change_execution_id=execution_id,
                status="ACTIVE",
            )
            self.db.add(run)
        elif run.app_key_id != app_key_id or run.environment != self.environment:
            raise PermissionDeniedError("执行记录已绑定其他应用")
        if run.revoked_at is not None or run.status != "ACTIVE":
            raise PermissionDeniedError("运行已关闭")
        run.credential_digest = self._digest(token)
        run.credential_expires_at = utcnow() + timedelta(minutes=10)
        self.db.flush()
        # Recheck actual source identity; a policy authorization never creates a login session.
        self._context(run, connection, touch_session=False)
        return run, token

    @atomic_write
    def issue_objection(self, app_key_id: str, job_id: int):
        """Trusted dispatcher only; bind a claimed precheck without committing its parent."""
        from app.modules.agent.objection_runtime import service_for_job

        connection = self._connection(app_key_id)
        if connection.entry_kind != "AUTOMATION" or connection.workflow_kind != "objection":
            raise PermissionDeniedError("该应用不是申诉预审工作流")
        service = service_for_job(self.db, job_id)
        job, row = service._execution(job_id)
        service._assert_attempt(job, job.attempt_token)
        if job.environment != self.environment or not service._current(job, row, lock_files=True):
            raise PermissionDeniedError("预审来源不属于当前环境或已变化")
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.objection_precheck_job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        token = secrets.token_urlsafe(32)
        if run is None:
            run = AgentRun(
                app_key_id=app_key_id,
                entry_kind="AUTOMATION",
                workflow_kind="objection",
                environment=self.environment,
                actor_user_id=job.initiated_by_user_id,
                source_session_id=None,
                college_id=job.college_id,
                semester_id=row[2].semester_id,
                objection_precheck_job_id=job.id,
                status="ACTIVE",
            )
            self.db.add(run)
        elif run.app_key_id != app_key_id or run.environment != self.environment:
            raise PermissionDeniedError("预审任务已绑定其他应用")
        if run.revoked_at is not None or run.status != "ACTIVE":
            raise PermissionDeniedError("运行已关闭")
        run.objection_precheck_attempt_digest = self._digest(job.attempt_token)
        run.credential_digest = self._digest(token)
        run.credential_expires_at = utcnow() + timedelta(minutes=10)
        self.db.flush()
        self._context(run, connection, touch_session=False)
        return run, token

    def _context(self, run, connection, *, touch_session):
        if run.entry_kind == "AUTOMATION":
            from app.modules.agent.change_runtime import change_context

            if connection.workflow_kind != run.workflow_kind:
                raise PermissionDeniedError("后台工作流配置已变化")
            if run.workflow_kind == "change":
                return change_context(self.db, run)
            if run.workflow_kind == "objection":
                from app.modules.agent.objection_runtime import objection_context

                return objection_context(self.db, run)
            raise PermissionDeniedError("未实现的后台工作流")
        if (
            run.source_session_id is None
            or run.workflow_kind is not None
            or run.auto_change_execution_id is not None
            or run.objection_precheck_job_id is not None
            or run.objection_precheck_attempt_digest is not None
        ):
            raise PermissionDeniedError("运行来源无效")
        actor = self._actor(run.actor_user_id, run.source_session_id, touch_session=touch_session)
        return RunContext(str(run.id), run.entry_kind, actor, run.college_id, run.semester_id)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def authenticate(self, app_key: str) -> AppConnection:
        if not 32 <= len(app_key) <= 512:
            raise UnauthenticatedError("工具应用凭据无效")
        digest = self._digest(app_key)
        for connection in self.connections:
            if connection.environment == self.environment and secrets.compare_digest(
                digest, connection.key_digest
            ):
                return connection
        raise UnauthenticatedError("工具应用凭据无效")

    def resolve(self, app_key: str, run_token: str) -> RunContext:
        connection = self.authenticate(app_key)
        if not 32 <= len(run_token) <= 512:
            raise PermissionDeniedError("运行凭据无效或已过期")
        run = self.db.scalar(
            select(AgentRun)
            .where(AgentRun.credential_digest == self._digest(run_token))
            .execution_options(populate_existing=True)
        )
        if (
            run is None
            or run.app_key_id != connection.app_key_id
            or run.entry_kind != connection.entry_kind
            or run.environment != self.environment
            or not self._resolvable(run)
            or run.revoked_at is not None
            or run.credential_expires_at <= utcnow()
        ):
            raise PermissionDeniedError("运行凭据无效或已过期")
        return self._context(run, connection, touch_session=True)

    def restore(self, run_id: int) -> RunContext:
        """Trusted Worker path; queue life is independent of incoming token TTL."""
        run = self.db.scalar(
            select(AgentRun).where(AgentRun.id == run_id).execution_options(populate_existing=True)
        )
        if (
            run is None
            or run.environment != self.environment
            or not self._resolvable(run)
            or run.revoked_at is not None
        ):
            raise PermissionDeniedError("运行已关闭")
        connection = self._connection(run.app_key_id)
        if connection.entry_kind != run.entry_kind:
            raise PermissionDeniedError("应用入口已变化")
        return self._context(run, connection, touch_session=False)

    @staticmethod
    def _resolvable(run) -> bool:
        # Completed prechecks can only replay the exact saved advice receipt.
        # The workflow runtime continues to forbid case/material reads in this state.
        return run.status == "ACTIVE" or (
            run.entry_kind == "AUTOMATION"
            and run.workflow_kind == "objection"
            and run.status == "COMPLETED"
        )

    def rotate(self, run_id: int, user_id: int, session_id: int) -> str:
        return self._rotate(run_id, user_id, session_id, commit=True)

    @atomic_write
    def rotate_in_transaction(self, run_id: int, user_id: int, session_id: int) -> str:
        return self._rotate(run_id, user_id, session_id, commit=False)

    def _rotate(self, run_id: int, user_id: int, session_id: int, *, commit: bool) -> str:
        self._actor(user_id, session_id, touch_session=commit)
        run = self.db.scalar(
            select(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.actor_user_id == user_id,
                AgentRun.source_session_id == session_id,
            )
            .with_for_update()
        )
        if run is None:
            raise NotFoundError()
        self._connection(run.app_key_id)
        if (
            run.environment != self.environment
            or run.status != "ACTIVE"
            or run.revoked_at is not None
        ):
            raise PermissionDeniedError("运行已关闭")
        token = secrets.token_urlsafe(32)
        run.credential_digest = self._digest(token)
        run.credential_expires_at = utcnow() + timedelta(minutes=10)
        self.db.flush()
        if commit:
            self.db.commit()
        return token
