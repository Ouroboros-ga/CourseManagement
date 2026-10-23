"""Change responsibility on the same unexecuted task, then explicitly schedule again."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db, utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import Semester, TeachingClass
from app.modules.academic.time_router import require_scheduling_enabled
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.deps import CurrentUserDep
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.role_scope import business_today
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    TaskRosterMember,
    TaskScheduleSource,
)
from app.modules.organization.router import require_campus_enabled
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write
from app.modules.volunteer.models import VolunteerGroup
from app.modules.volunteer.policy import InspectionScope


class TransferSelection(StrictModel):
    target_group_id: int = Field(gt=0, lt=2**63)
    lock_version: int = Field(ge=0)


class TransferCommit(TransferSelection):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(default="", max_length=512)


class TaskGroupTransferService:
    def __init__(self, db, actor, cid):
        self.db, self.actor, self.cid = db, actor, cid

    def _prepare(self, tid, target_gid, version, *, lock_anchors=False):
        scope = resolve_scope(self.db, self.actor, self.cid, "assignment.manage", write=True)
        probe = self.db.scalar(
            select(InspectionTask).where(InspectionTask.id == tid, scope.task_condition())
        )
        if probe is None:
            raise NotFoundError()
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == probe.semester_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None or semester.status != "ACTIVE":
            raise ConflictError(message="学期已停用")
        group = self.db.scalar(
            select(VolunteerGroup)
            .where(VolunteerGroup.id == target_gid, VolunteerGroup.college_id == self.cid)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if group is None or group.status != "ACTIVE":
            raise NotFoundError("目标组不存在或未启用")
        previous = self.db.scalar(
            select(InspectionAssignment).where(
                InspectionAssignment.task_id == tid, InspectionAssignment.revoked_at.is_(None)
            )
        )
        expected_assignment = (previous.id, previous.lock_version) if previous else None
        if lock_anchors and previous:
            from app.modules.inspection.scoped_service import ScopedInspectionService

            ScopedInspectionService(self.db, self.actor, self.cid)._lock_day_anchors(
                {(previous.volunteer_user_id, probe.inspection_date)}
            )
        task = self.db.scalar(
            select(InspectionTask)
            .where(InspectionTask.id == tid, scope.task_condition())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None:
            raise NotFoundError()
        if task.lock_version != version or task.canceled_at is not None:
            raise ConflictError(message="任务已变化或已取消")
        if task.inspection_date < business_today():
            raise ConflictError(message="历史任务不允许更换执行组")
        if task.teaching_class_id is None:
            raise ConflictError(message="旧任务缺少明确教学班来源，不能猜测换组分类")
        if self.db.scalar(
            select(InspectionSubmission.id).where(InspectionSubmission.task_id == tid).limit(1)
        ) or self.db.scalar(
            see_withdrawn(
                select(AttendanceRecord.id).where(AttendanceRecord.task_id == tid).limit(1)
            )
        ):
            raise ConflictError(message="任务已有提交或考勤，不允许更换执行组或规则快照")
        from app.modules.volunteer.preparation_models import semester_group_config
        config = semester_group_config(self.db, group, semester.id)
        if config is None:
            raise ConflictError(message="目标组尚未发布范围")
        teaching_ids = set(
            self.db.scalars(
                select(TaskScheduleSource.teaching_class_id).where(
                    TaskScheduleSource.task_id == tid
                )
            )
        )
        if task.teaching_class_id:
            teaching_ids.add(task.teaching_class_id)
        classes = list(
            self.db.scalars(
                select(TeachingClass)
                .where(TeachingClass.id.in_(teaching_ids))
                .with_for_update(read=True)
            )
        )
        types = {row.course_type_id for row in classes}
        if (
            not classes
            or len(classes) != len(teaching_ids)
            or len(types) != 1
            or None in types
            or any(row.status != "ACTIVE" or row.college_id != self.cid for row in classes)
        ):
            raise ConflictError(message="任务来源分类不完整或合班分类不一致，请先处理来源")
        kind = self.db.scalar(
            select(CourseType)
            .where(
                CourseType.id == next(iter(types)),
                CourseType.college_id == self.cid,
                CourseType.status == "ACTIVE",
            )
            .with_for_update(read=True)
        )
        roster = set(
            self.db.scalars(
                select(TaskRosterMember.administrative_class_id_snapshot).where(
                    TaskRosterMember.task_id == tid,
                    TaskRosterMember.roster_version == task.roster_version,
                )
            )
        )
        if task.administrative_class_id:
            roster.add(task.administrative_class_id)
        cfg = config.configuration
        rule = InspectionScope(
            self.cid,
            frozenset(int(x) for x in cfg["course_type_ids"]),
            frozenset(int(x) for x in cfg.get("class_ids", []))
            if cfg["class_mode"] == "SPECIFIC"
            else None,
        )
        if (
            kind is None
            or not rule.allows(college_id=self.cid, course_type_id=kind.id, class_ids=roster)
            or not scope.permits_plan(target_gid, kind.id, teaching_ids, roster)
        ):
            raise ConflictError(message="任务超出目标组或操作者的授权范围")
        if (group.starts_on and task.inspection_date < group.starts_on) or (
            group.ends_on and task.inspection_date > group.ends_on
        ):
            raise ConflictError(message="任务日期超出目标组有效期")
        assignment = self.db.scalar(
            select(InspectionAssignment)
            .where(InspectionAssignment.task_id == tid, InspectionAssignment.revoked_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if expected_assignment != (
            (assignment.id, assignment.lock_version) if assignment else None
        ):
            raise ConflictError(message="任务受派在锁定期间变化，请重新预览")
        source = {
            "task": [task.id, task.lock_version, task.group_id, task.group_config_version_id],
            "group": [group.id, group.lock_version, config.id],
            "source": [
                (r.id, r.course_type_id, r.classification_revision)
                for r in sorted(classes, key=lambda r: r.id)
            ],
            "assignment": [assignment.id, assignment.lock_version] if assignment else None,
            "authorization": scope.authorization_revision,
            "roster": sorted(roster, key=str),
        }
        return task, group, config, kind, classes, assignment, fingerprint(source)

    def preview(self, tid, body):
        task, group, config, kind, classes, assignment, revision = self._prepare(
            tid, body.target_group_id, body.lock_version
        )
        return {
            "task_id": str(task.id),
            "target_group_id": str(group.id),
            "course_type_id": str(kind.id),
            "revision": revision,
            "lock_version": task.lock_version,
            "will_revoke_assignment": assignment is not None,
            "requires_new_assignment": True,
            "same_group_rule_refresh": task.group_id == group.id,
        }

    @atomic_write
    def commit(self, tid, body):
        task, group, config, kind, classes, assignment, revision = self._prepare(
            tid, body.target_group_id, body.lock_version, lock_anchors=True
        )
        if revision != body.revision:
            raise ConflictError(message="任务、受派、来源或目标组已变化，请重新预览")
        before = {
            "group_id": str(task.group_id) if task.group_id else None,
            "config_version_id": str(task.group_config_version_id),
            "course_type_id": str(task.course_type_id_snapshot),
            "assignment_id": str(assignment.id) if assignment else None,
        }
        if assignment:
            assignment.revoked_at = utcnow()
            assignment.lock_version += 1
            for request in self.db.scalars(
                select(AssignmentChangeRequest)
                .where(
                    AssignmentChangeRequest.assignment_id == assignment.id,
                    AssignmentChangeRequest.status == "PENDING",
                )
                .with_for_update()
            ):
                request.status, request.processed_by, request.processed_at = (
                    "REJECTED",
                    self.actor.id,
                    utcnow(),
                )
                request.comment = "任务执行组/规则已变更，原调班申请失效"
        task.group_id, task.group_config_version_id = group.id, config.id
        task.group_name_snapshot = group.name
        task.course_type_id_snapshot, task.course_type_name_snapshot = kind.id, kind.name
        task.classification_revision_snapshot = next(
            row.classification_revision for row in classes if row.id == task.teaching_class_id
        )
        task.lock_version += 1
        after = {
            "task_id": str(task.id),
            "group_id": str(group.id),
            "lock_version": task.lock_version,
            "requires_new_assignment": True,
        }
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="inspection.task.group.transfer",
                resource_type="inspection_task",
                resource_id=str(task.id),
                before_json=before,
                after_json={**after, "_workspace_college_id": str(self.cid)},
                reason=body.reason,
            )
        )
        self.db.commit()
        return after


router = APIRouter(
    tags=["task-group-transfer"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scheduling_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
Id = Annotated[int, Path(gt=0, le=2**63 - 1)]


@router.post("/colleges/{cid}/inspection-tasks/{tid}/execution-group/preview")
def preview(cid: Id, tid: Id, body: TransferSelection, actor: CurrentUserDep, db: Db):
    return success(TaskGroupTransferService(db, actor, cid).preview(tid, body))


@router.post("/colleges/{cid}/inspection-tasks/{tid}/execution-group/confirm")
def confirm(cid: Id, tid: Id, body: TransferCommit, actor: CurrentUserDep, db: Db):
    return success(TaskGroupTransferService(db, actor, cid).commit(tid, body))
