"""Only time constraints for already-authorized volunteers, including unclassified legacy courses.

Never returns another college's students, course names or task rosters to a management API.
Core predicates bind every private read to the provided volunteer/student IDs.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select

from app.models import Base


def course_times(db, semester_id: int, student_ids: list[int], teaching_days):
    if not student_ids:
        return {}
    t = Base.metadata.tables
    schedule, weeks = t["course_schedule"], t["course_schedule_week"]
    legacy, participation, audience = (
        t["teaching_class_student"],
        t["course_participation"],
        t["teaching_class_audience"],
    )
    enrollment, student = t["student_enrollment"], t["student"]
    legacy_pairs = list(
        db.execute(
            select(legacy.c.teaching_class_id, legacy.c.student_id).where(
                legacy.c.student_id.in_(student_ids)
            )
        )
    )
    dated = list(
        db.execute(
            select(participation).where(participation.c.student_id.in_(student_ids))
        ).mappings()
    )
    classes = list(
        db.execute(select(enrollment).where(enrollment.c.student_id.in_(student_ids))).mappings()
    )
    current = {
        r.id: r
        for r in db.execute(
            select(student.c.id, student.c.administrative_class_id, student.c.status).where(
                student.c.id.in_(student_ids)
            )
        )
    }
    class_ids = {r["administrative_class_id"] for r in classes if r["administrative_class_id"]} | {
        r.administrative_class_id for r in current.values() if r.administrative_class_id
    }
    source_pairs = list(
        db.execute(
            select(audience.c.teaching_class_id, audience.c.administrative_class_id).where(
                audience.c.administrative_class_id.in_(class_ids)
            )
        )
    )
    tids = (
        {r[0] for r in legacy_pairs}
        | {r["teaching_class_id"] for r in dated}
        | {r[0] for r in source_pairs}
    )
    if not tids:
        return {}
    class_driven = set(
        db.scalars(
            select(audience.c.teaching_class_id).where(audience.c.teaching_class_id.in_(tids))
        )
    )
    schedules = list(
        db.execute(
            select(
                schedule.c.teaching_class_id,
                schedule.c.weekday,
                weeks.c.week_no,
                schedule.c.start_period,
                schedule.c.end_period,
            )
            .join(weeks, weeks.c.schedule_id == schedule.c.id)
            .where(
                schedule.c.semester_id == semester_id,
                schedule.c.status == "ACTIVE",
                schedule.c.teaching_class_id.in_(tids),
            )
        )
    )
    has_dates = {r["student_id"] for r in classes}
    dated_pairs = {(r["teaching_class_id"], r["student_id"]) for r in dated}
    result = defaultdict(list)
    for day, teaching in teaching_days.items():
        if teaching is None:
            continue
        active_classes = {}
        for sid in student_ids:
            e = next(
                (
                    r
                    for r in reversed(classes)
                    if r["student_id"] == sid
                    and not r["superseded"]
                    and r["effective_from"] <= day
                    and (r["effective_to"] is None or day < r["effective_to"])
                ),
                None,
            )
            if e and e["status"] == "ENROLLED":
                active_classes[sid] = e["administrative_class_id"]
            elif sid not in has_dates and sid in current and current[sid].status == "ACTIVE":
                active_classes[sid] = current[sid].administrative_class_id
        pairs = {
            (tid, sid)
            for tid, sid in legacy_pairs
            if tid not in class_driven and (tid, sid) not in dated_pairs and sid in active_classes
        }
        pairs.update(
            (r["teaching_class_id"], r["student_id"])
            for r in dated
            if r["student_id"] in active_classes
            and r["effective_from"] <= day
            and (r["effective_to"] is None or day < r["effective_to"])
        )
        pairs.update(
            (tid, sid)
            for tid, acid in source_pairs
            for sid, cid in active_classes.items()
            if cid == acid
        )
        for tid, weekday, week, start, end in schedules:
            if (week, weekday) == teaching:
                for candidate_tid, sid in pairs:
                    if tid == candidate_tid:
                        result[sid, day].append((start, end))
    return result


@dataclass
class AssignmentTime:
    id: int
    semester_id: int
    inspection_date: date
    start_period: int
    end_period: int
    classroom_snapshot: str | None
    college_id: int | None = None
    group_id: int | None = None
    group_config_version_id: int | None = None
    activity_start_at: datetime | None = None
    activity_end_at: datetime | None = None
    time_snapshot: dict | None = None


def assignment_times(db, volunteer_ids: list[int], dates, *, lock=False):
    t = Base.metadata.tables
    task, assignment = t["inspection_task"], t["inspection_assignment"]
    statement = select(assignment.c.volunteer_user_id, *task.c).join(
        task, task.c.id == assignment.c.task_id
    ).where(assignment.c.volunteer_user_id.in_(volunteer_ids),
            assignment.c.revoked_at.is_(None), task.c.canceled_at.is_(None),
            task.c.inspection_date.in_(dates))
    if lock:
        statement = statement.with_for_update(read=True)
    return [(r.volunteer_user_id, AssignmentTime(
        r.id, r.semester_id, r.inspection_date, r.start_period, r.end_period,
        r.classroom_snapshot, r.college_id, r.group_id, r.group_config_version_id,
        r.activity_start_at, r.activity_end_at, r.time_snapshot,
    )) for r in db.execute(statement)]


def assignment_loads(db, semester_id: int, volunteer_ids: list[int]):
    from sqlalchemy import func

    t = Base.metadata.tables
    task, assignment = t["inspection_task"], t["inspection_assignment"]
    return dict(
        db.execute(
            select(assignment.c.volunteer_user_id, func.count())
            .join(task, task.c.id == assignment.c.task_id)
            .where(
                task.c.semester_id == semester_id,
                assignment.c.volunteer_user_id.in_(volunteer_ids),
                assignment.c.revoked_at.is_(None),
                task.c.canceled_at.is_(None),
            )
            .group_by(assignment.c.volunteer_user_id)
        ).all()
    )
