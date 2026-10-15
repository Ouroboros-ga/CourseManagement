"""All roster writers use the same college/occurrence/student occupancy constraint."""

from sqlalchemy import ForeignKey, String, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db import MYSQL_TABLE_ARGS
from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.academic.models import CourseSchedule
from app.modules.inspection.models import InspectionTask, TaskRosterMember, TaskScheduleSource
from app.modules.organization.models import College


class InspectionResponsibility(Base):
    __tablename__ = "inspection_responsibility"
    __table_args__ = (MYSQL_TABLE_ARGS,)
    college_id: Mapped[int] = mapped_column(
        ForeignKey("college.id", ondelete="RESTRICT"), primary_key=True
    )
    occurrence_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="RESTRICT"), primary_key=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), index=True
    )


def schedule_occurrence(schedule, day):
    key = (
        schedule.shared_meeting_key
        if schedule.shared_identity_from and day >= schedule.shared_identity_from
        else None
    )
    return f"{key or f's:{schedule.id}'}|{day.isoformat()}"


def task_occurrences(db, task):
    if task.occurrence_keys_snapshot:
        return task.occurrence_keys_snapshot
    ids = set(
        db.scalars(
            select(TaskScheduleSource.course_schedule_id).where(
                TaskScheduleSource.task_id == task.id
            )
        )
    )
    if task.course_schedule_id:
        ids.add(task.course_schedule_id)
    if ids:
        # Historical tasks predate confirmed sharing and retain their private identity.
        return [f"s:{sid}|{task.inspection_date.isoformat()}" for sid in sorted(ids)]
    return [
        f"{task.inspection_type}:a:{task.administrative_class_id or task.teaching_class_id}|"
        f"{task.inspection_date}|{task.start_period}-{task.end_period}"
    ]


def sync_responsibility(db, task):
    """Caller holds normal action scope; no commit here, including cancellations.

    The college anchor serializes absent-row checks. The composite primary key is
    the final database guard, independent of groups, request keys or roster order.
    """
    if task.college_id is None:
        return
    db.scalar(select(College.id).where(College.id == task.college_id).with_for_update())
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.inspection.models import TaskDeadlineAssessment

    if (
        task.canceled_at
        and not db.scalar(
            select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id).limit(1)
        )
        and not db.scalar(
            select(TaskDeadlineAssessment.id)
            .where(TaskDeadlineAssessment.task_id == task.id)
            .limit(1)
        )
    ):
        db.execute(
            delete(InspectionResponsibility).where(InspectionResponsibility.task_id == task.id)
        )
        return
    students = sorted(
        set(
            db.scalars(
                select(TaskRosterMember.student_id).where(
                    TaskRosterMember.task_id == task.id,
                    TaskRosterMember.roster_version == task.roster_version,
                )
            )
        )
    )
    keys = sorted(set(task_occurrences(db, task)))
    conflicts = set()
    # Bounded chunks avoid huge SQL packets when a merged task has a large roster.
    for start in range(0, len(students), 400):
        conflicts.update(
            db.scalars(
                select(InspectionResponsibility.student_id).where(
                    InspectionResponsibility.college_id == task.college_id,
                    InspectionResponsibility.occurrence_key.in_(keys),
                    InspectionResponsibility.student_id.in_(students[start : start + 400]),
                    InspectionResponsibility.task_id != task.id,
                )
            )
        )
    if conflicts:
        raise AppError(
            ErrorCode.STATE_CONFLICT,
            "本院该课次已有重叠学生的有效检查任务，整批未保存",
            409,
            field_errors={"conflicting_student_count": len(conflicts)},
        )
    db.execute(delete(InspectionResponsibility).where(InspectionResponsibility.task_id == task.id))
    db.add_all(
        [
            InspectionResponsibility(
                college_id=task.college_id, occurrence_key=key, student_id=sid, task_id=task.id
            )
            for key in keys
            for sid in students
        ]
    )
    db.flush()


def normalize_plan(service, plan):
    """Compute stable identities read-only; display name, room and roster aren't identities."""
    from app.modules.academic.offerings import assert_shared_consistent
    from app.modules.inspection.assignment_fingerprint import fingerprint

    ids = plan.constituent_schedule_ids or (
        [plan.course_schedule_id] if plan.course_schedule_id else []
    )
    schedules = list(
        service._session.scalars(select(CourseSchedule).where(CourseSchedule.id.in_(ids)))
    )
    for tid in {s.teaching_class_id for s in schedules}:
        checked = getattr(service, "_shared_identity_checked", set())
        if tid not in checked:
            assert_shared_consistent(service._session, tid)
            checked.add(tid)
            service._shared_identity_checked = checked
    plan.occurrence_keys = sorted({schedule_occurrence(s, plan.inspection_date) for s in schedules})
    if not plan.occurrence_keys:
        return plan
    allowed = service._repo.college_ids
    if allowed is None or len(allowed) != 1:
        raise ConflictError(message="生成检查须明确任务负责学院")
    cid = next(iter(allowed))
    gid = service._generation_group[0].id if service._generation_group else 0
    roster_hash = fingerprint(sorted(m.student_id for m in plan.roster))[:24]
    occurrence_hash = fingerprint(plan.occurrence_keys)[:24]
    plan.task_key = f"c{cid}|{plan.inspection_date}|o{occurrence_hash}|r{roster_hash}|g{gid}"
    # Reuse exact legacy requests without changing their IDs or historical keys.
    existing = list(
        service._session.scalars(
            select(InspectionTask).where(
                InspectionTask.college_id == cid,
                InspectionTask.inspection_date == plan.inspection_date,
                InspectionTask.group_id == gid if gid else InspectionTask.group_id.is_(None),
                InspectionTask.canceled_at.is_(None),
                InspectionTask.course_schedule_id.in_(ids),
            )
        )
    )
    for task in existing:
        members = set(
            service._session.scalars(
                select(TaskRosterMember.student_id).where(
                    TaskRosterMember.task_id == task.id,
                    TaskRosterMember.roster_version == task.roster_version,
                )
            )
        )
        if members == {m.student_id for m in plan.roster} and set(
            task_occurrences(service._session, task)
        ) == set(plan.occurrence_keys):
            plan.task_key = task.task_key
            break
    return plan


def available_plans(service, plans, *, strict):
    if not plans:
        return plans
    college_id = next(iter(service._repo.college_ids))
    keys = {key for p in plans for key in p.occurrence_keys}
    rows = service._session.execute(
        select(
            InspectionResponsibility.occurrence_key,
            InspectionResponsibility.student_id,
            InspectionTask.task_key,
        )
        .join(InspectionTask, InspectionTask.id == InspectionResponsibility.task_id)
        .where(
            InspectionResponsibility.college_id == college_id,
            InspectionResponsibility.occurrence_key.in_(keys),
        )
    ).all()
    occupied = {}
    for row in rows:
        occupied.setdefault(row.occurrence_key, []).append(row)
    result = []
    for plan in plans:
        students = {m.student_id for m in plan.roster}
        conflicts = {
            r.student_id
            for key in plan.occurrence_keys
            for r in occupied.get(key, [])
            if r.student_id in students and r.task_key != plan.task_key
        }
        if conflicts:
            if strict:
                raise AppError(
                    ErrorCode.STATE_CONFLICT,
                    "本院所选课次已有重叠学生的有效检查任务",
                    409,
                    field_errors={"conflicting_student_count": len(conflicts)},
                )
            continue
        result.append(plan)
    return result
