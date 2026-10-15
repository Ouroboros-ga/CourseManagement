"""Explicit approval, common day locks and immutable existing assignments."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester, Student
from app.modules.identity.models import UserAccount
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.service import InspectionService
from app.modules.organization.impact_service import assignment_snapshot, capture_impacts
from app.modules.organization.models import College
from app.modules.organization.schemas import StrictModel
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.member_models import VolunteerGroupMember
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.unavailability_models import VolunteerUnavailability


class UnavailabilityCreate(StrictModel):
    student_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(default="", max_length=512)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.second or value.microsecond:
            raise ValueError("起止时间须包含时区并使用分钟精度")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid(self):
        if any(int(value) >= 2**63 for value in (self.student_id, self.semester_id)):
            raise ValueError("标识超出范围")
        if self.starts_at >= self.ends_at or self.ends_at - self.starts_at > timedelta(days=420):
            raise ValueError("起止时间无效或超过学期长度上限")
        return self


class UnavailabilityDecision(StrictModel):
    impact_revision: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")
    lock_version: int = Field(ge=1)
    status: Literal["APPROVED", "REJECTED", "CANCELED"]
    note: str = Field(default="", max_length=512)


class UnavailabilityWithdrawal(StrictModel):
    lock_version: int = Field(ge=1)
    status: Literal["CANCELED"] = "CANCELED"
    note: str = Field(default="", max_length=512)


def local_days(start, end):
    offset = timedelta(hours=get_settings().app_utc_offset_hours)
    first, last = (start + offset).date(), (end + offset - timedelta(microseconds=1)).date()
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


class UnavailabilityService:
    def __init__(self, db, actor, cid, gid):
        self.db, self.actor, self.cid, self.gid = db, actor, cid, gid
        self.members = GroupMemberService(db, actor, cid, gid)
        self.campus = self.members.campus

    def _dto(self, row, student=None):
        student = student if student is not None else self.db.get(Student, row.student_id)
        return {
            **self.campus._dto(row),
            "name": student.name if student else None,
            "student_no": student.student_no if student else None,
            "scope": "ALL_GROUPS",
        }

    def _record(self, rid, *, lock=False):
        stmt = select(VolunteerUnavailability).where(
            VolunteerUnavailability.id == rid,
            VolunteerUnavailability.college_id == self.cid,
            VolunteerUnavailability.group_id == self.gid,
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.scalar(stmt.execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError()
        return row

    def list(self, sid, *, page=1, own=False):
        if own:
            self.campus._actor(self.actor)
            student_id = self.db.get(UserAccount, self.actor.id).student_id
            if student_id is None:
                raise PermissionDeniedError("未绑定学生")
        else:
            self.members._group("volunteer.group.read")
            student_id = None
        stmt = select(VolunteerUnavailability).where(
            VolunteerUnavailability.college_id == self.cid,
            VolunteerUnavailability.group_id == self.gid,
            VolunteerUnavailability.semester_id == sid,
        )
        if own:
            stmt = stmt.where(VolunteerUnavailability.student_id == student_id)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = list(
            self.db.scalars(
                stmt.order_by(VolunteerUnavailability.id.desc()).offset((page - 1) * 50).limit(50)
            )
        )
        students = {
            student.id: student
            for student in self.db.scalars(
                select(Student).where(Student.id.in_({row.student_id for row in rows}))
            )
        }
        return {
            "items": [self._dto(row, students.get(row.student_id)) for row in rows],
            "total": total,
        }

    @atomic_write
    def create(self, data, *, own=False):
        body = validated(UnavailabilityCreate, data)
        if own:
            self.campus._actor(self.actor, lock=not own)
            account = self.db.get(UserAccount, self.actor.id)
            if account.student_id != int(body.student_id):
                raise PermissionDeniedError("只能为本人申请")
            college = self.campus.repo.college(self.cid, lock=True)
            if college is None or college.status != "ACTIVE":
                raise NotFoundError()
            from app.modules.volunteer.models import VolunteerGroup

            group = self.campus._resource(VolunteerGroup, self.cid, self.gid)
        else:
            college, group = self.members._group(
                "volunteer.member.manage", write=True, semester_id=int(body.semester_id)
            )
        if group.status != "ACTIVE":
            raise ConflictError(message="仅有效组可以申请不可用时段")
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == int(body.semester_id))
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        start, end = body.starts_at.replace(tzinfo=None), body.ends_at.replace(tzinfo=None)
        days = local_days(start, end)
        if (
            semester is None
            or semester.status != "ACTIVE"
            or not semester.start_date <= days[0] <= days[-1] <= semester.end_date
        ):
            raise ConflictError(message="不可用时段须在有效学期内")
        membership = self.db.scalar(
            select(VolunteerGroupMember.id)
            .where(
                VolunteerGroupMember.college_id == self.cid,
                VolunteerGroupMember.group_id == self.gid,
                VolunteerGroupMember.semester_id == semester.id,
                VolunteerGroupMember.student_id == int(body.student_id),
                VolunteerGroupMember.status == "ACTIVE",
                VolunteerGroupMember.effective_from <= days[0],
                VolunteerGroupMember.effective_to > days[-1],
            )
            .with_for_update(read=True)
            .limit(1)
        )
        if membership is None:
            raise NotFoundError("申请人不是覆盖整段日期的有效组成员")
        row = VolunteerUnavailability(
            college_id=self.cid,
            group_id=self.gid,
            student_id=int(body.student_id),
            semester_id=semester.id,
            starts_at=start,
            ends_at=end,
            reason=body.reason,
            requested_by=self.actor.id,
        )
        self.db.add(row)
        return {
            **self.campus._commit(self.actor, "volunteer.unavailability.request", row),
            "scope": "ALL_GROUPS",
        }

    def _affected(self, row, *, lock=False):
        days = local_days(row.starts_at, row.ends_at)
        stmt = (
            select(InspectionTask)
            .join(InspectionAssignment, InspectionAssignment.task_id == InspectionTask.id)
            .join(UserAccount, UserAccount.id == InspectionAssignment.volunteer_user_id)
            .where(
                UserAccount.student_id == row.student_id,
                InspectionAssignment.revoked_at.is_(None),
                InspectionTask.canceled_at.is_(None),
                InspectionTask.inspection_date >= days[0],
                InspectionTask.inspection_date <= days[-1],
                or_(
                    InspectionTask.activity_start_at.is_(None),
                    InspectionTask.activity_end_at.is_(None),
                    (InspectionTask.activity_start_at < row.ends_at)
                    & (InspectionTask.activity_end_at > row.starts_at),
                ),
            )
        )
        if lock:
            stmt = stmt.with_for_update()
        return list(
            self.db.scalars(
                stmt.order_by(InspectionTask.id).execution_options(populate_existing=True)
            )
        )

    def _impact_revision(self, row, affected, *, lock=False):
        return fingerprint(
            {
                "request": [row.id, row.lock_version, row.status],
                "tasks": [(task.id, task.lock_version) for task in affected],
                "assignments": assignment_snapshot(
                    self.db, [task.id for task in affected], lock=lock
                ),
            }
        )

    def impact(self, rid, *, own=False):
        if own:
            self.campus._actor(self.actor)
            row = self._record(rid)
            if self.db.get(UserAccount, self.actor.id).student_id != row.student_id:
                raise NotFoundError()
        else:
            self.members._group("volunteer.group.read")
            row = self._record(rid)
        affected = self._affected(row)
        return {
            "revision": self._impact_revision(row, affected),
            "lock_version": row.lock_version,
            "retained_assignment_count": len(affected),
            "scope": "ALL_GROUPS",
            "existing_assignments_preserved": True,
        }

    @atomic_write
    def decide(self, rid, data, *, own=False):
        body = validated(UnavailabilityDecision, data)
        self.campus._actor(self.actor, lock=not own)
        probe = self._record(rid)
        # Lock every affected college in ascending order before group/day/task locks.
        # An approval may affect other colleges, but their task IDs/reasons are not disclosed.
        college_ids = {self.cid} | {
            task.college_id for task in self._affected(probe) if task.college_id is not None
        }
        list(
            self.db.scalars(
                select(College)
                .where(College.id.in_(college_ids))
                .order_by(College.id)
                .with_for_update()
            )
        )
        if own:
            if (
                body.status != "CANCELED"
                or self.db.get(UserAccount, self.actor.id).student_id != probe.student_id
            ):
                raise PermissionDeniedError("只能撤回本人的申请")
            self.db.scalar(
                select(Semester.id).where(Semester.id == probe.semester_id).with_for_update()
            )
        else:
            _, group = self.members._group(
                "volunteer.member.manage", write=True, semester_id=probe.semester_id
            )
            if body.status == "APPROVED" and group.status != "ACTIVE":
                raise ConflictError(message="组已停用，不能批准新的不可用时段")
        users = list(
            self.db.scalars(
                select(UserAccount.id).where(UserAccount.student_id == probe.student_id)
            )
        )
        InspectionService(self.db)._lock_day_anchors(
            {(uid, day) for uid in users for day in local_days(probe.starts_at, probe.ends_at)}
        )
        row = self._record(rid, lock=True)
        if row.lock_version != body.lock_version:
            raise ConflictError(message="申请已变化，请刷新")
        if (
            (row.status == "PENDING" and body.status not in {"APPROVED", "REJECTED", "CANCELED"})
            or (row.status == "APPROVED" and body.status != "CANCELED")
            or row.status in {"REJECTED", "CANCELED"}
        ):
            raise ConflictError(message="申请状态不允许此操作")
        affected = self._affected(row, lock=True)
        if any(task.college_id not in college_ids for task in affected):
            raise ConflictError(message="受派的学院范围已变化或尚未确认，请核对后重新审批")
        if body.status == "APPROVED":
            semester_status = self.db.scalar(
                select(Semester.status)
                .where(Semester.id == row.semester_id)
                .with_for_update(read=True)
            )
            student_status = self.db.scalar(
                select(Student.status)
                .where(Student.id == row.student_id)
                .with_for_update(read=True)
            )
            if semester_status != "ACTIVE" or student_status != "ACTIVE":
                raise ConflictError(message="学期或学生已停用，不能批准新的申请")
            days = local_days(row.starts_at, row.ends_at)
            member = self.db.scalar(
                select(VolunteerGroupMember.id)
                .where(
                    VolunteerGroupMember.group_id == self.gid,
                    VolunteerGroupMember.student_id == row.student_id,
                    VolunteerGroupMember.semester_id == row.semester_id,
                    VolunteerGroupMember.status == "ACTIVE",
                    VolunteerGroupMember.effective_from <= days[0],
                    VolunteerGroupMember.effective_to > days[-1],
                )
                .with_for_update(read=True)
                .limit(1)
            )
            if member is None:
                raise ConflictError(message="成员有效期已变化，不能批准此申请")
            if body.impact_revision != self._impact_revision(row, affected, lock=True):
                raise ConflictError(message="申请或已有受派已变化，请重新查看影响后批准")
        before = self.campus._dto(row)
        row.status, row.lock_version = body.status, row.lock_version + 1
        row.decided_by, row.decided_at, row.decision_note = self.actor.id, utcnow(), body.note
        # Availability never deletes assignments or changes deadline/attendance facts.
        if body.status == "APPROVED":
            for cid in sorted(
                {task.college_id for task in affected if task.college_id is not None}
            ):
                capture_impacts(
                    self.db,
                    cid,
                    "unavailability",
                    row.id,
                    row.lock_version,
                    task_ids=[task.id for task in affected if task.college_id == cid],
                    after={
                        "student_id": str(row.student_id),
                        "starts_at": row.starts_at.isoformat(),
                        "ends_at": row.ends_at.isoformat(),
                        "status": row.status,
                    },
                )
        result = self.campus._commit(self.actor, "volunteer.unavailability.decide", row, before)
        return {**result, "scope": "ALL_GROUPS", "retained_assignment_count": len(affected)}
