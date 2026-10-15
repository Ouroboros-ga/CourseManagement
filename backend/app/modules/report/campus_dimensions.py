"""Keep task ownership, historical student affiliation and deduplication distinct."""

from collections import Counter, defaultdict

from sqlalchemy import select

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.attendance.models import AttendanceRecord
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.models import InspectionSubmission, InspectionTask, TaskRosterMember
from app.modules.inspection.responsibility import task_occurrences
from app.modules.organization.models import College
from app.modules.organization.service import CampusService


class CampusDimensionsService:
    def __init__(self, db, actor, sid, cid=None):
        self.db, self.actor, self.sid, self.cid = db, actor, sid, cid

    def summary(self):
        predicate = True
        if self.cid is None:
            is_super = CampusService(self.db)._actor(self.actor)
            if not is_super and "statistics.school.read" not in IdentityRepository(
                self.db
            ).list_effective_permissions(self.actor.id):
                raise PermissionDeniedError("全校汇总需要明确的校级汇总查看权限")
        else:
            predicate = resolve_scope(
                self.db, self.actor, self.cid, "statistics.read"
            ).task_condition()
        if self.db.get(Semester, self.sid) is None:
            raise NotFoundError("学期不存在")
        tasks = list(
            self.db.scalars(
                select(InspectionTask).where(
                    InspectionTask.semester_id == self.sid,
                    InspectionTask.canceled_at.is_(None),
                    predicate,
                )
            )
        )
        by_id = {t.id: t for t in tasks}
        approved = select(InspectionSubmission.task_id).where(
            InspectionSubmission.review_status == "APPROVED"
        )
        rows = list(
            self.db.execute(
                select(
                    AttendanceRecord.task_id,
                    AttendanceRecord.student_id,
                    AttendanceRecord.effective_type,
                    TaskRosterMember.college_id_snapshot,
                )
                .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .outerjoin(
                    TaskRosterMember,
                    (TaskRosterMember.task_id == InspectionTask.id)
                    & (TaskRosterMember.roster_version == InspectionTask.roster_version)
                    & (TaskRosterMember.student_id == AttendanceRecord.student_id),
                )
                .where(AttendanceRecord.task_id.in_(by_id), AttendanceRecord.task_id.in_(approved))
            )
        )
        keys = {t.id: task_occurrences(self.db, t) for t in tasks}
        groups = defaultdict(list)
        for row in rows:
            groups[by_id[row.task_id].college_id, row.college_id_snapshot].append(row)
        names = {c.id: c.name for c in self.db.scalars(select(College))}

        def metrics(records):
            return {
                "checked_task_count": len({r.task_id for r in records}),
                "check_person_times": len(records),
                "distinct_student_count": len({r.student_id for r in records}),
                "distinct_student_occurrence_count": len(
                    {(r.student_id, key) for r in records for key in keys[r.task_id]}
                ),
                "result_distribution": dict(Counter(r.effective_type for r in records)),
            }

        return {
            "semester_id": str(self.sid),
            "task_count": len(tasks),
            **metrics(rows),
            "aggregation_scope": "TASK_RESPONSIBLE_COLLEGE",
            "student_college_basis": "TASK_ROSTER_SNAPSHOT",
            "deduplication_note": (
                "按已确认课次身份去重；未关联的教学班独立计数。"
                "结果分布为检查人次，不形成全校统一考勤结论。"
            ),
            "dimensions": [
                {
                    "responsible_college_id": str(owner) if owner else None,
                    "responsible_college_name": names.get(owner),
                    "student_college_id_snapshot": str(student) if student else None,
                    "student_college_name": names.get(student),
                    **metrics(records),
                }
                for (owner, student), records in sorted(
                    groups.items(), key=lambda pair: str(pair[0])
                )
            ],
        }
