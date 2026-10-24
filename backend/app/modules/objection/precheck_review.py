"""Prepared, transaction-bound authorization for the existing final-review core."""

from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.agent.models import AgentRun
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.models import InspectionTask
from app.modules.objection.models import Objection
from app.modules.objection.precheck_management import PrecheckManagementService
from app.modules.objection.precheck_schemas import PrecheckResult
from app.modules.objection.precheck_service import ObjectionPrecheckService


@dataclass(frozen=True)
class ReviewState:
    can_review: bool
    manual_required: bool = False
    block_reason: str | None = None
    current: bool = False
    valid_advice: bool = False
    unavailable: bool = False


def review_state(domain, row, job, *, lock=False):
    if row[0].final_status != "PENDING" or row[1].effect_state != "EFFECTIVE":
        return ReviewState(False, block_reason="申诉已完成或考勤已撤回")
    semester = select(Semester.status).where(Semester.id == row[2].semester_id)
    if lock:
        semester = semester.with_for_update(read=True)
    if domain.db.scalar(semester) == "ARCHIVED":
        return ReviewState(False, block_reason="该学期已归档，仅可查看")
    if job is None:
        policy = domain._policy(lock=lock)
        if policy and policy.enabled and PrecheckManagementService.configuration_ready():
            return ReviewState(False, block_reason="请先发起申诉预审")
        return ReviewState(True, manual_required=True, unavailable=True)
    current = domain._current(job, row, lock_files=lock)
    if current and job.status in {"QUEUED", "RUNNING"}:
        query = select(AgentRun.id).where(AgentRun.objection_precheck_job_id == job.id)
        if lock:
            query = query.with_for_update()
        run = domain.db.scalar(query)
        if (
            job.status == "QUEUED"
            and run is None
            and not PrecheckManagementService.configuration_ready()
        ):
            return ReviewState(True, manual_required=True, current=True, unavailable=True)
        return ReviewState(False, block_reason="预审仍在处理中，请等待预审完成", current=True)
    if current and job.status == "SUCCEEDED":
        try:
            PrecheckResult.model_validate(job.result_json)
        except ValueError:
            pass
        else:
            return ReviewState(True, current=True, valid_advice=True)
    return ReviewState(True, manual_required=True, current=current)


def review_options(domain, actor, row, job):
    actual = domain._actor(actor.id)
    try:
        if not {"SUPER_ADMIN", "TEACHER_ADMIN"}.intersection(actual.roles):
            raise PermissionDeniedError()
        scope = resolve_scope(domain.db, actual, domain.cid, "objection.final_review")
        if (
            domain.db.scalar(
                select(InspectionTask.id).where(
                    InspectionTask.id == row[2].id, scope.task_condition()
                )
            )
            is None
        ):
            raise PermissionDeniedError()
    except (PermissionDeniedError, NotFoundError):
        return {
            "can_final_review": False,
            "manual_reason_required": False,
            "review_block_reason": "须由当前授权范围内的教务管理员终审",
        }
    state = review_state(domain, row, job)
    return {
        "can_final_review": state.can_review,
        "manual_reason_required": state.manual_required,
        "review_block_reason": state.block_reason,
    }


class PreparedFinalReview:
    def __init__(self, db, actor_id, domain, row, scope):
        self.db, self.actor_id, self.domain, self.row, self.scope = db, actor_id, domain, row, scope
        self.transaction = db.get_transaction()

    @classmethod
    def prepare(cls, db, actor_id, objection_id):
        actual = ObjectionPrecheckService(db, None)._actor(actor_id)
        if not {"SUPER_ADMIN", "TEACHER_ADMIN"}.intersection(actual.roles):
            raise PermissionDeniedError("智能预审启用后，须由授权教务管理员终审")
        college_id = db.scalar(
            select(InspectionTask.college_id)
            .join(AttendanceRecord, AttendanceRecord.task_id == InspectionTask.id)
            .join(Objection, Objection.attendance_record_id == AttendanceRecord.id)
            .where(Objection.id == objection_id)
        )
        if college_id is None:
            raise NotFoundError("申诉负责学院未明确或记录不存在")
        scope = resolve_scope(db, actual, college_id, "objection.final_review", write=True)
        domain = ObjectionPrecheckService(db, college_id)
        row = domain._open_source(objection_id)
        if (
            db.scalar(
                select(InspectionTask.id).where(
                    InspectionTask.id == row[2].id, scope.task_condition()
                )
            )
            is None
        ):
            raise NotFoundError("申诉不在当前终审范围")
        return cls(db, actor_id, domain, row, scope)

    def accept(self, db, actor_id, obj, record, body):
        if (
            self.db is not db
            or self.actor_id != actor_id
            or self.transaction is None
            or self.transaction is not db.get_transaction()
            or self.row[0].id != obj.id
            or self.row[1].id != record.id
            or self.scope.actor_user_id != actor_id
            or self.scope.action != "objection.final_review"
        ):
            raise PermissionDeniedError("教务终审上下文已失效，请重新打开申诉")
        management = PrecheckManagementService(db, self.domain.cid)
        job = management._latest(obj.id, lock=True)
        expected = str(job.id) if job else None
        if body.precheck_job_id != expected:
            raise ConflictError(message="预审记录已变化，请刷新核对后终审")
        reason = body.manual_precheck_reason
        state = review_state(self.domain, self.row, job, lock=True)
        if not state.can_review:
            raise ConflictError(message=state.block_reason)
        if state.manual_required and not reason:
            raise ConflictError(message="预审失败或已失效，请重试或记录人工核验原因")
        if job is None:
            policy = self.domain._policy(lock=True)
            digest = self.domain._snapshot(self.row, lock_files=True)[0]
            job = self.domain._create_job(self.row, actor_id, policy, digest)
        if state.unavailable:
            job.status, job.error_code = "FAILED", "PRECHECK_UNAVAILABLE"
        if not state.valid_advice:
            if job.status in {"QUEUED", "RUNNING"}:
                job.status, job.error_code = "STALE", "SOURCE_CHANGED"
            job.attempt_token = None
        run = db.scalar(
            select(AgentRun)
            .where(AgentRun.objection_precheck_job_id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is not None:
            run.revoked_at = run.revoked_at or utcnow()
        return {
            "job_id": str(job.id),
            "college_id": str(self.domain.cid),
            "mode": "AI_ASSISTED" if state.valid_advice else "MANUAL_FALLBACK",
            "stored_status": job.status,
            "effective_status": (
                "INVALID_RESULT"
                if job.status == "SUCCEEDED" and state.current and not state.valid_advice
                else job.status
                if state.current or state.unavailable
                else "STALE"
            ),
            "manual_reason": reason,
        }


def prepare_if_enabled(db, actor_id, objection_id):
    if not get_settings().agent_objection_precheck_enabled:
        return None
    return PreparedFinalReview.prepare(db, actor_id, objection_id)
