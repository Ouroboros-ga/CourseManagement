"""学生本人办理进度；不返回内部执行或AI建议，也不推进任何业务状态。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.models import UserAccount
from app.modules.identity.query_scope import activate_query_scope
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from app.modules.objection.models import Objection
from app.modules.objection.precheck_models import ObjectionPrecheckJob, ObjectionPrecheckPolicy
from app.modules.objection.precheck_service import ObjectionPrecheckService
from app.modules.objection.service import ObjectionService

ProgressStage = Literal[
    "SUBMITTED",
    "PRECHECK_QUEUED",
    "PRECHECK_RUNNING",
    "ACADEMIC_REVIEW",
    "COMPLETED",
    "RECORD_WITHDRAWN",
    "ARCHIVED",
]
MESSAGES = {
    "SUBMITTED": ("已提交", "申诉已保留，等待教务受理。"),
    "PRECHECK_QUEUED": ("等待预审", "申诉已进入预审队列，尚未形成正式结论。"),
    "PRECHECK_RUNNING": ("正在预审", "正在整理申诉与材料，最终结论以教务审核为准。"),
    "ACADEMIC_REVIEW": ("等待教务审核", "请等待教务管理员核验；预审意见不代表申诉通过或驳回。"),
    "COMPLETED": ("审核已完成", "请查看正式审核结果及当前考勤认定。"),
    "RECORD_WITHDRAWN": ("考勤记录已撤回", "原考勤已撤回，本申诉仅保留历史记录。"),
    "ARCHIVED": ("学期已归档", "本申诉仅可查看历史，处理事宜请联系教务管理员。"),
}


class StudentObjectionProgress(BaseModel):
    objection_id: str
    stage: ProgressStage
    label: str
    description: str
    final_status: Literal["PENDING", "APPROVED", "REJECTED"]
    updated_at: datetime | None


class StudentObjectionProgressResponse(BaseModel):
    data: StudentObjectionProgress
    requestId: str | None


class StudentObjectionProgressService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, actor: CurrentUser, objection_id: int) -> StudentObjectionProgress:
        settings = get_settings()
        if not settings.agent_objection_precheck_enabled:
            raise NotFoundError()
        # 本人入口不继承管理学院筛选，所有权由下面两项student_id共同限制。
        activate_query_scope(self.db, actor.id, personal=True)
        identity = ObjectionService(self.db)
        identity._require(actor.id, "objection.read")
        account = self.db.get(UserAccount, actor.id)
        if account is None or not account.is_active:
            raise PermissionDeniedError("账号不可用")
        sid = account.student_id
        if sid is None:
            raise NotFoundError("申诉不存在或不可查看")
        statement = see_withdrawn(
            select(Objection, AttendanceRecord, InspectionTask)
            .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
            .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
            .where(
                Objection.id == objection_id,
                Objection.student_id == sid,
                AttendanceRecord.student_id == sid,
            )
        )
        row = self.db.execute(statement.execution_options(populate_existing=True)).one_or_none()
        if row is None:
            raise NotFoundError("申诉不存在或不可查看")
        objection, record, task = row
        stage: ProgressStage = "SUBMITTED"
        updated_at: datetime | None = objection.updated_at
        if record.effect_state != "EFFECTIVE":
            stage, updated_at = "RECORD_WITHDRAWN", None
        elif objection.final_status != "PENDING":
            stage = "COMPLETED"
        elif (
            self.db.scalar(select(Semester.status).where(Semester.id == task.semester_id))
            == "ARCHIVED"
        ):
            stage, updated_at = "ARCHIVED", None
        else:
            job = self.db.scalar(
                select(ObjectionPrecheckJob)
                .where(
                    ObjectionPrecheckJob.objection_id == objection.id,
                    ObjectionPrecheckJob.college_id == task.college_id,
                    ObjectionPrecheckJob.environment == settings.app_env,
                )
                .order_by(ObjectionPrecheckJob.id.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if job is not None:
                current = ObjectionPrecheckService(self.db, task.college_id)._current(job, row)
                policy = self.db.scalar(
                    select(ObjectionPrecheckPolicy)
                    .where(ObjectionPrecheckPolicy.college_id == task.college_id)
                    .execution_options(populate_existing=True)
                )
                policy_current = bool(
                    policy
                    and policy.enabled
                    and policy.id == job.policy_id
                    and policy.version == job.policy_version
                    and policy.authorizer_user_id == job.authorizer_user_id
                )
                stage, updated_at = "ACADEMIC_REVIEW", None
                if current and policy_current:
                    if job.status == "QUEUED":
                        stage = "PRECHECK_QUEUED"
                    elif job.status == "RUNNING":
                        stage = "PRECHECK_RUNNING"
                    updated_at = job.updated_at
        label, description = MESSAGES[stage]
        return StudentObjectionProgress(
            objection_id=str(objection.id),
            stage=stage,
            label=label,
            description=description,
            final_status=objection.final_status,
            updated_at=updated_at,
        )
