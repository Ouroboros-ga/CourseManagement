"""正式课表的实际分钟忙碌；与个人显示课表无依赖。"""

from collections import defaultdict
from datetime import date

from sqlalchemy import or_, select, union
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError
from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
)
from app.modules.academic.roster_index import RosterIndex
from app.modules.academic.time_service import TimeResolver


def formal_course_slots(db: Session, student_ids: set[int], days: set[date], *, lock=False):
    slots: defaultdict[tuple[int, date], list[tuple[int, int, int, int | None]]] = defaultdict(list)
    if not student_ids or not days:
        return slots
    classes = union(
        select(StudentEnrollment.administrative_class_id).where(
            StudentEnrollment.student_id.in_(student_ids),
            StudentEnrollment.superseded.is_(False),
            StudentEnrollment.effective_from <= max(days),
            or_(
                StudentEnrollment.effective_to.is_(None), StudentEnrollment.effective_to > min(days)
            ),
        ),
        select(Student.administrative_class_id).where(Student.id.in_(student_ids)),
    )
    teaching_ids = union(
        select(TeachingClassStudent.teaching_class_id).where(
            TeachingClassStudent.student_id.in_(student_ids)
        ),
        select(CourseParticipation.teaching_class_id).where(
            CourseParticipation.student_id.in_(student_ids)
        ),
        select(TeachingClassAudience.teaching_class_id).where(
            TeachingClassAudience.administrative_class_id.in_(classes)
        ),
    )
    statement = (
        select(CourseSchedule, TeachingClass, Semester)
        .options(selectinload(CourseSchedule.weeks))
        .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
        .join(Course, Course.id == TeachingClass.course_id)
        .join(Semester, Semester.id == CourseSchedule.semester_id)
        .where(
            CourseSchedule.teaching_class_id.in_(teaching_ids),
            CourseSchedule.status == "ACTIVE",
            TeachingClass.status == "ACTIVE",
            Course.status == "ACTIVE",
            Semester.start_date <= max(days),
            Semester.end_date >= min(days),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(read=True)
    rows = list(db.execute(statement))
    index = RosterIndex(db, [tc.id for _, tc, _ in rows], lock=lock, student_ids=student_ids)
    resolver = TimeResolver(db)
    for cid, sid in {(tc.college_id, sem.id) for _, tc, sem in rows if tc.college_id is not None}:
        resolver.prefetch(cid, sid, lock=lock)
    for day in sorted(days):
        roster = index.at(day)
        for schedule, teaching, semester in rows:
            if not semester.start_date <= day <= semester.end_date:
                continue
            attendees = [s.id for s in roster.get(teaching.id, []) if s.id in student_ids]
            if not attendees:
                continue
            if (
                teaching.semester_id != schedule.semester_id
                or teaching.college_id != schedule.college_id
            ):
                raise ConflictError(message="本人正式课程父链归属不一致，不能判断空闲")
            effective = resolver.teaching_day(teaching.college_id, semester.id, day)
            if (
                effective is None
                or schedule.weekday != effective[1]
                or not any(w.week_no == effective[0] for w in schedule.weeks)
            ):
                continue
            interval = resolver.interval(
                teaching.college_id, semester.id, day, schedule.start_period, schedule.end_period
            )
            for sid in attendees:
                slots[sid, day].append(
                    (
                        interval["start_minute"],
                        interval["end_minute"],
                        teaching.id,
                        getattr(teaching, "course_type_id", None),
                    )
                )
    return slots
