"""Explicit school-semester closure and a narrow audited correction exception."""

from pydantic import Field
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from app.modules.objection.models import Objection
from app.modules.organization.impact_models import ConfigurationImpactItem
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import CampusService, atomic_write, validated
from app.modules.report.models import Report, ReportVersion


def require_open_task(db, task_id):
    sid = db.scalar(select(InspectionTask.semester_id).where(InspectionTask.id == task_id))
    status = db.scalar(select(Semester.status).where(Semester.id == sid).with_for_update(read=True))
    if status == "ARCHIVED":
        raise ConflictError(message="该学期已归档；历史纠错请由授权教师使用归档更正入口")


class ArchiveRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=512)


class ArchiveConfirm(ArchiveRequest):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class SemesterArchiveService:
    def __init__(self, db, actor, sid):
        self.db, self.actor, self.sid = db, actor, sid

    def _preview(self, data):
        CampusService(self.db)._super(self.actor)
        body = validated(ArchiveRequest, data)
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == self.sid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None:
            raise NotFoundError("学期不存在")
        tasks = list(
            self.db.execute(
                select(InspectionTask.id, InspectionTask.lock_version)
                .where(
                    InspectionTask.semester_id == self.sid,
                    InspectionTask.canceled_at.is_(None),
                    ~select(InspectionSubmission.id)
                    .where(
                        InspectionSubmission.task_id == InspectionTask.id,
                        InspectionSubmission.review_status == "APPROVED",
                    )
                    .exists(),
                )
                .order_by(InspectionTask.id)
            )
        )
        objections = list(
            self.db.scalars(
                select(Objection.id)
                .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
                .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .where(InspectionTask.semester_id == self.sid, Objection.final_status == "PENDING")
                .order_by(Objection.id)
            )
        )
        impacts = list(
            self.db.scalars(
                select(ConfigurationImpactItem.id)
                .join(InspectionTask, InspectionTask.id == ConfigurationImpactItem.task_id)
                .where(
                    InspectionTask.semester_id == self.sid, ConfigurationImpactItem.status == "OPEN"
                )
                .order_by(ConfigurationImpactItem.id)
            )
        )
        reports = list(
            self.db.execute(
                select(ReportVersion.id, ReportVersion.status)
                .join(Report, Report.id == ReportVersion.report_id)
                .where(Report.semester_id == self.sid)
                .order_by(ReportVersion.id)
            )
        )
        blockers = {
            "unfinished_task_ids": [str(r.id) for r in tasks],
            "pending_objection_ids": [str(i) for i in objections],
            "open_impact_ids": [str(i) for i in impacts],
            "generating_report_version_ids": [
                str(r.id) for r in reports if r.status == "GENERATING"
            ],
        }
        preview = {
            "semester_id": str(semester.id),
            "status": semester.status,
            "blockers": blockers,
            "can_archive": semester.status == "ACTIVE" and not any(blockers.values()),
            "published_report_version_ids": [str(r.id) for r in reports if r.status == "PUBLISHED"],
            "persistent_assets_retained": True,
        }
        preview["revision"] = fingerprint(
            {
                "actor": self.actor.id,
                "reason": body.reason,
                "semester": CampusService(self.db)._dto(semester),
                "tasks": [list(t) for t in tasks],
                "preview": preview,
            }
        )
        return body, semester, preview

    def preview(self, data):
        return self._preview(data)[2]

    @atomic_write
    def confirm(self, data):
        body = validated(ArchiveConfirm, data)
        _, semester, preview = self._preview(body.model_dump(exclude={"revision"}))
        if body.revision != preview["revision"] or not preview["can_archive"]:
            raise ConflictError(message="归档条件已变化或仍有未完成事项，请先处置后重新预览")
        semester.status = "ARCHIVED"
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="academic.semester.archive",
                resource_type="semester",
                resource_id=str(semester.id),
                after_json={**preview, "reason": body.reason},
            )
        )
        self.db.commit()
        return {
            "semester_id": str(semester.id),
            "status": semester.status,
            "persistent_assets_retained": True,
        }
