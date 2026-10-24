"""预审领域事务。仅供受信任后端调用，尚未暴露为AI工具或公网接口。

策略和资料归属始终由后端确定；模型只提交结构化建议。
执行锁序为学院/策略→查课任务→考勤→异议→预审任务→材料。
创建申诉时的enqueue只读取策略快照，不在持有考勤/文件锁时反向等待策略锁。
"""

import hashlib
import json
import secrets

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileObject
from app.modules.file.service import FileService
from app.modules.file.storage import StorageBackend
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from app.modules.objection.models import Objection, ObjectionFile
from app.modules.objection.precheck_models import ObjectionPrecheckJob, ObjectionPrecheckPolicy
from app.modules.objection.precheck_schemas import PrecheckResult
from app.modules.organization.service import atomic_write


class ObjectionPrecheckService:
    def __init__(self, db, college_id: int | None, *, storage: StorageBackend | None = None):
        self.db, self.cid = db, college_id
        self.storage = storage

    def _enabled(self):
        if not get_settings().agent_objection_precheck_enabled:
            raise NotFoundError("申诉预审尚未启用")

    def _policy(self, *, lock=False):
        if self.cid is None:
            return None
        statement = select(ObjectionPrecheckPolicy).where(
            ObjectionPrecheckPolicy.college_id == self.cid
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalar(statement.execution_options(populate_existing=True))

    def _actor(self, user_id):
        repo = IdentityRepository(self.db)
        user = repo.get_user_by_id(user_id)
        if user is None or user.status != "ACTIVE":
            raise PermissionDeniedError("预审策略授权人不可用")
        return CurrentUser(
            user.id,
            user.username,
            user.display_name,
            user.status,
            repo.list_effective_role_codes(user.id),
            repo.list_effective_permissions(user.id),
        )

    def _policy_authority(self, actor, *, write=True):
        # 角色和范围均从数据库重读，不能把学生负责人或缓存标签当成学院授权人。
        actual = self._actor(actor.id)
        if not {"SUPER_ADMIN", "TEACHER_ADMIN"}.intersection(actual.roles):
            raise PermissionDeniedError("仅学院教师管理员可设置预审策略")
        for action in ("objection.read", "objection.final_review"):
            if not resolve_scope(self.db, actual, self.cid, action, write=write).unrestricted:
                raise PermissionDeniedError("预审策略需要完整学院范围")
        return actual

    @atomic_write
    def set_policy(self, actor, *, enabled: bool, current_version: int):
        self._enabled()
        self._policy_authority(actor)
        policy = self._policy(lock=True)
        if current_version != (policy.version if policy else 0):
            raise ConflictError(message="预审策略已变化，请刷新")
        if policy is None:
            policy = ObjectionPrecheckPolicy(college_id=self.cid, version=0)
            self.db.add(policy)
        policy.enabled, policy.authorizer_user_id = enabled, actor.id
        policy.version += 1
        self.db.flush()
        view = {"enabled": policy.enabled, "version": policy.version}
        self.db.add(
            AuditLog(
                actor_user_id=actor.id,
                action="objection.precheck.policy",
                resource_type="objection_precheck_policy",
                resource_id=str(policy.id),
                after_json={**view, "college_id": str(self.cid)},
            )
        )
        self.db.commit()
        return view

    def _source(self, objection_id, *, lock=False):
        statement = see_withdrawn(
            select(Objection, AttendanceRecord, InspectionTask)
            .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
            .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
            .where(Objection.id == objection_id, InspectionTask.college_id == self.cid)
        )
        row = self.db.execute(statement.execution_options(populate_existing=True)).one_or_none()
        if row is None:
            raise NotFoundError()
        obj, record, task = row
        if lock:
            locked = []
            for model, key in (
                (InspectionTask, task.id),
                (AttendanceRecord, record.id),
                (Objection, obj.id),
            ):
                current = self.db.scalar(
                    see_withdrawn(
                        select(model).where(model.id == key).with_for_update()
                    ).execution_options(populate_existing=True)
                )
                if current is None:
                    raise NotFoundError()
                locked.append(current)
            task, record, obj = locked
            if (
                task.college_id != self.cid
                or record.task_id != task.id
                or obj.attendance_record_id != record.id
            ):
                raise NotFoundError()
            # Do not issue an ordinary SELECT after these current reads: MySQL RR may
            # otherwise replace the locked values with the older transaction snapshot.
        return obj, record, task

    def _open_source(self, objection_id):
        from app.modules.academic.archive import require_open_task

        initial = self._source(objection_id)
        semester_id = initial[2].semester_id
        # Read-lock semester closure before task locks to avoid reversing archive's order.
        require_open_task(self.db, initial[2].id)
        row = self._source(objection_id, lock=True)
        if row[2].semester_id != semester_id:
            raise ConflictError(message="申诉关联学期已变化，请刷新")
        return row

    def _files(self, objection_id, *, lock=False):
        statement = (
            select(FileObject)
            .join(ObjectionFile, ObjectionFile.file_id == FileObject.id)
            .where(ObjectionFile.objection_id == objection_id)
            .order_by(FileObject.id)
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalars(statement.execution_options(populate_existing=True)).all()

    def _snapshot(self, row, *, lock_files=False):
        obj, record, task = row
        files = self._files(obj.id, lock=lock_files)
        payload = {
            "objection": [
                str(obj.id),
                str(obj.student_id),
                obj.base_attendance_version,
                obj.reason,
                obj.desired_type,
                obj.final_status,
            ],
            "attendance": [
                str(record.id),
                record.current_version,
                record.effective_type,
                record.effect_state,
            ],
            "task": {
                name: str(getattr(task, name))
                for name in (
                    "id",
                    "college_id",
                    "semester_id",
                    "inspection_date",
                    "start_period",
                    "end_period",
                    "course_name_snapshot",
                    "class_name_snapshot",
                    "canceled_at",
                    "lock_version",
                    "classroom_snapshot",
                    "teacher_name_snapshot",
                    "deleted_at",
                )
            },
            "files": [
                {
                    name: str(getattr(f, name))
                    for name in (
                        "id",
                        "sha256",
                        "status",
                        "category",
                        "size_bytes",
                        "content_type",
                        "original_name",
                        "uploader_user_id",
                        "expires_at",
                        "purged_at",
                    )
                }
                for f in files
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return digest, {str(f.id) for f in files}

    def enqueue(self, objection_id, initiated_by_user_id):
        """Flush-only source event. Caller owns authorization and the creation transaction."""
        self._enabled()
        row = self._source(objection_id)
        digest, _ = self._snapshot(row)
        policy = self._policy()  # No policy lock after the creator's attendance/file locks.
        version = policy.version if policy else 0
        env = get_settings().app_env
        job = self.db.scalar(
            select(ObjectionPrecheckJob)
            .where(
                ObjectionPrecheckJob.objection_id == objection_id,
                ObjectionPrecheckJob.source_digest == digest,
                ObjectionPrecheckJob.policy_version == version,
                ObjectionPrecheckJob.environment == env,
            )
            .order_by(ObjectionPrecheckJob.attempt_no.desc(), ObjectionPrecheckJob.id.desc())
            .limit(1)
        )
        if job is not None:
            return job
        return self._create_job(row, initiated_by_user_id, policy, digest)

    def _create_job(
        self, row, initiated_by_user_id, policy, digest, *, attempt_no=1, retry_of=None
    ):
        """Flush-only registration from a trusted, scoped snapshot."""
        available = policy is not None and policy.enabled
        pending = row[0].final_status == "PENDING" and row[1].effect_state == "EFFECTIVE"
        job = ObjectionPrecheckJob(
            objection_id=row[0].id,
            college_id=self.cid,
            environment=get_settings().app_env,
            source_digest=digest,
            initiated_by_user_id=initiated_by_user_id,
            policy_id=policy.id if policy else None,
            policy_version=policy.version if policy else 0,
            attempt_no=attempt_no,
            retry_of_job_id=retry_of,
            authorizer_user_id=policy.authorizer_user_id if policy else None,
            status="QUEUED" if available and pending else "FAILED",
            error_code=None
            if available and pending
            else (
                "SOURCE_CLOSED"
                if not pending
                else ("SOURCE_SCOPE_UNRESOLVED" if self.cid is None else "POLICY_UNAVAILABLE")
            ),
        )
        self.db.add(job)
        self.db.flush()
        return job

    def _job(self, job_id, *, lock=False):
        statement = select(ObjectionPrecheckJob).where(
            ObjectionPrecheckJob.id == job_id,
            ObjectionPrecheckJob.college_id == self.cid,
            ObjectionPrecheckJob.environment == get_settings().app_env,
        )
        if lock:
            statement = statement.with_for_update()
        job = self.db.scalar(statement.execution_options(populate_existing=True))
        if job is None:
            raise NotFoundError()
        return job

    def _execution(self, job_id):
        self._enabled()
        initial = self._job(job_id)
        if initial.authorizer_user_id is None:
            raise PermissionDeniedError("申诉预审未取得授权")
        self._policy_authority(self._actor(initial.authorizer_user_id))
        policy = self._policy(lock=True)
        if (
            policy is None
            or not policy.enabled
            or policy.id != initial.policy_id
            or policy.version != initial.policy_version
            or policy.authorizer_user_id != initial.authorizer_user_id
        ):
            raise PermissionDeniedError("预审策略已关闭或发生变化")
        row = self._open_source(initial.objection_id)
        return self._job(job_id, lock=True), row

    def _current(self, job, row, *, lock_files=False):
        return (
            row[0].final_status == "PENDING"
            and row[1].effect_state == "EFFECTIVE"
            and job.source_digest == self._snapshot(row, lock_files=lock_files)[0]
        )

    @atomic_write
    def begin(self, job_id):
        token = self.begin_in_transaction(job_id)
        self.db.commit()
        return token

    def begin_in_transaction(self, job_id):
        """Flush-only claim, allowing cloud tracking and identity to commit with it."""
        job, row = self._execution(job_id)
        if job.status != "QUEUED":
            raise ConflictError(message="预审任务已经领取或结束")
        if not self._current(job, row, lock_files=True):
            job.status, job.error_code = "STALE", "SOURCE_CHANGED"
            self.db.flush()
            return None
        job.attempt_token = secrets.token_hex(32)
        job.status = "RUNNING"
        self.db.flush()
        return job.attempt_token

    @atomic_write
    def finish(self, job_id, attempt_token, result: PrecheckResult):
        status = self.finish_in_transaction(job_id, attempt_token, result)
        self.db.commit()
        return status

    def finish_in_transaction(self, job_id, attempt_token, result: PrecheckResult):
        """Flush-only core so the trusted runtime can commit its receipt atomically."""
        job, row = self._execution(job_id)
        self._assert_attempt(job, attempt_token)
        if not self._current(job, row, lock_files=True):
            job.status, job.error_code, job.attempt_token = "STALE", "SOURCE_CHANGED", None
        else:
            result = PrecheckResult.model_validate(result.model_dump())
            file_ids = self._snapshot(row, lock_files=True)[1]
            if any(e.source == "PROOF" and e.file_id not in file_ids for e in result.evidence):
                raise NotFoundError("材料不属于当前申诉")
            encoded = result.model_dump_json()
            if len(encoded.encode()) > 32768:
                raise ConflictError(message="预审结果超过保存限制")
            job.status, job.result_json, job.attempt_token = "SUCCEEDED", result.model_dump(), None
            self._audit_access(job, "objection.precheck.complete")
        self.db.flush()
        return job.status

    @staticmethod
    def _assert_attempt(job, attempt_token):
        if (
            job.status != "RUNNING"
            or not attempt_token
            or not job.attempt_token
            or not secrets.compare_digest(job.attempt_token, attempt_token)
        ):
            raise ConflictError(message="预审执行批次已失效")

    def _audit_access(self, job, action, *, file_id=None):
        self.db.add(
            AuditLog(
                actor_user_id=None,
                action=action,
                resource_type="objection_precheck_job",
                resource_id=str(job.id),
                after_json={
                    "college_id": str(self.cid),
                    "objection_id": str(job.objection_id),
                    "policy_id": str(job.policy_id),
                    "policy_version": job.policy_version,
                    "authorizer_user_id": str(job.authorizer_user_id),
                    **({"file_id": str(file_id)} if file_id is not None else {}),
                },
            )
        )

    def _running_source(self, job_id, attempt_token):
        job, row = self._execution(job_id)
        self._assert_attempt(job, attempt_token)
        if not self._current(job, row, lock_files=True):
            raise ConflictError(message="申诉资料已变化，请重新发起预审")
        return job, row

    @atomic_write
    def case_get(self, job_id, attempt_token):
        job, (obj, record, task) = self._running_source(job_id, attempt_token)
        files = self._files(obj.id, lock=True)
        if len(files) > 20:
            raise ConflictError(message="材料数量超过自动预审限制，请人工处理")
        if files:
            actor = self._actor(job.authorizer_user_id)
            file_service = FileService(self.db, storage=self.storage)
            if any(
                f.category != "OBJECTION_PROOF" or not file_service.can_access(actor, f)
                for f in files
            ):
                raise NotFoundError("申诉材料不可读取")
        view = {
            "objection_id": str(obj.id),
            "reason": obj.reason,
            "desired_type": obj.desired_type,
            "attendance": {
                "current_version": record.current_version,
                "effective_type": record.effective_type,
            },
            "task": {
                "date": task.inspection_date.isoformat(),
                "start_period": task.start_period,
                "end_period": task.end_period,
                "course": task.course_name_snapshot,
                "class": task.class_name_snapshot,
            },
            "files": [
                {
                    "file_id": str(f.id),
                    "name": f.original_name,
                    "content_type": f.content_type,
                    "size_bytes": f.size_bytes,
                }
                for f in files
            ],
        }
        if len(json.dumps(view, ensure_ascii=False).encode()) > 32768:
            raise ConflictError(message="资料摘要超过自动预审限制，请人工处理")
        self._audit_access(job, "objection.precheck.case_read")
        self.db.commit()
        return view

    @atomic_write
    def file_access(self, job_id, attempt_token, file_id: int):
        job, (obj, _, _) = self._running_source(job_id, attempt_token)
        files = self._files(obj.id, lock=True)
        if type(file_id) is not int or not any(
            f.id == file_id and f.category == "OBJECTION_PROOF" for f in files
        ):
            raise NotFoundError("材料不属于当前申诉")
        actor = self._actor(job.authorizer_user_id)
        access = FileService(self.db, storage=self.storage).get_access(
            actor, file_id, delivery="proxy", max_ttl_seconds=60
        )
        self._audit_access(job, "objection.precheck.material_access", file_id=file_id)
        self.db.commit()
        return access

    def read(self, actor, job_id):
        self._enabled()
        scope = resolve_scope(self.db, actor, self.cid, "objection.read")
        job = self._job(job_id)
        row = self._source(job.objection_id)
        if (
            self.db.scalar(
                select(InspectionTask.id).where(
                    InspectionTask.id == row[2].id, scope.task_condition()
                )
            )
            is None
        ):
            raise NotFoundError()
        current = self._current(job, row)
        return {
            "id": str(job.id),
            "status": job.status if current else "STALE",
            "error_code": job.error_code if current else "SOURCE_CHANGED",
            "result": job.result_json if current and job.status == "SUCCEEDED" else None,
        }
