"""发布源批量读取与本人投影。正式名单是唯一来源，不按班级名称猜选课。"""

from collections import defaultdict
from datetime import time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.config import get_settings
from app.core.exceptions import AppError, ErrorCode, NotFoundError, PermissionDeniedError
from app.modules.academic.calendar import resolve_teaching_day
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.publication_models import (
    AcademicPublication,
    PublicationAudience,
    PublishedSchedule,
    PublishedScheduleStudent,
)
from app.modules.academic.roster_index import RosterIndex
from app.modules.academic.time_service import TimeResolver
from app.modules.identity.models import UserAccount
from app.modules.identity.resource_scope import ResourceScope


class AcademicPublicationRepository:
    def __init__(self, db: Session, scope: ResourceScope):
        if scope.action not in {"academic.read", "academic.manage"}:
            raise PermissionDeniedError()
        self.db, self.scope = db, scope

    def latest(self, semester_id: int):
        return self.db.scalar(
            select(AcademicPublication)
            .where(
                AcademicPublication.college_id == self.scope.college_id,
                AcademicPublication.semester_id == semester_id,
            )
            .order_by(AcademicPublication.version.desc())
            .limit(1)
        )

    def source(self, semester_id: int, *, lock: bool):
        def rows(stmt):
            if lock:
                stmt = stmt.with_for_update().execution_options(populate_existing=True)
            return self.db.execute(stmt)

        semester = rows(select(Semester).where(Semester.id == semester_id)).scalar_one_or_none()
        if semester is None:
            raise NotFoundError("学期不存在")
        if semester.status != "ACTIVE":
            raise AppError(ErrorCode.STATE_CONFLICT, "学期已归档，不能发布", 409)
        periods = {
            row.period_no: (row.start_time, row.end_time)
            for row in rows(
                select(PeriodDefinition)
                .where(PeriodDefinition.semester_id == semester_id)
                .order_by(PeriodDefinition.period_no)
            ).scalars()
        }
        calendar_rows = list(
            rows(
                select(CalendarOverride)
                .where(CalendarOverride.semester_id == semester_id)
                .order_by(CalendarOverride.date)
            ).scalars()
        )
        overrides = [
            {
                "date": str(row.date),
                "override_type": row.override_type,
                "source_teaching_week": row.source_teaching_week,
                "source_teaching_weekday": row.source_teaching_weekday,
            }
            for row in calendar_rows
        ]
        context = {
            "semester_id": str(semester.id),
            "semester_name": semester.name,
            "start_date": str(semester.start_date),
            "end_date": str(semester.end_date),
            "first_monday": str(semester.first_monday),
            "total_weeks": semester.total_weeks,
            "timezone": "Asia/Shanghai",
            "calendar_overrides": overrides,
        }
        schedules = list(
            rows(
                select(CourseSchedule, TeachingClass, Course)
                .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
                .join(Course, Course.id == TeachingClass.course_id)
                .where(
                    CourseSchedule.college_id == self.scope.college_id,
                    TeachingClass.college_id == self.scope.college_id,
                    CourseSchedule.semester_id == semester_id,
                    TeachingClass.semester_id == semester_id,
                    CourseSchedule.status == "ACTIVE",
                    TeachingClass.status == "ACTIVE",
                    Course.status == "ACTIVE",
                )
                .order_by(CourseSchedule.id)
            )
        )
        teaching_ids = sorted({teaching.id for _, teaching, _ in schedules})
        schedule_ids = [schedule.id for schedule, _, _ in schedules]
        weeks = defaultdict(list)
        for sid, week in rows(
            select(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
            .where(CourseScheduleWeek.schedule_id.in_(schedule_ids))
            .order_by(CourseScheduleWeek.schedule_id, CourseScheduleWeek.week_no)
        ):
            weeks[sid].append(week)
        if (semester.end_date - semester.start_date).days > 420:
            raise AppError(ErrorCode.VALIDATION_ERROR, "学期跨度超过 60 周，不能发布", 422)
        index = RosterIndex(self.db, teaching_ids, lock=lock)
        calendar_map = {row.date: row for row in calendar_rows}
        resolver = None
        if get_settings().campus_scheduling_enabled:
            resolver = TimeResolver(self.db)
            versions = resolver.prefetch(self.scope.college_id, semester_id, lock=lock)
            context["college_time_versions"] = [
                {
                    "id": str(v.id),
                    "version": v.version,
                    "effective_from": str(v.effective_from),
                    "configuration": v.configuration,
                }
                for v in sorted(versions, key=lambda v: v.version)
            ]
        audiences: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        timed_audiences: dict[int, dict[tuple[int, int], dict[int, list[str]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        day = semester.start_date
        while day <= semester.end_date:
            teaching_day = (
                resolver.teaching_day(self.scope.college_id, semester_id, day)
                if resolver
                else resolve_teaching_day(semester.first_monday, day, calendar_map.get(day))
            )
            matched = [
                s
                for s, _, _ in schedules
                if teaching_day is not None
                and teaching_day[0] in weeks[s.id]
                and teaching_day[1] == s.weekday
            ]
            if matched:
                roster = index.at(day)
                for schedule in matched:
                    timing = None
                    if resolver:
                        interval = resolver.interval(
                            self.scope.college_id,
                            semester_id,
                            day,
                            schedule.start_period,
                            schedule.end_period,
                        )
                        timing = (interval["start_minute"], interval["end_minute"])
                        timed_audiences[schedule.id][timing]
                    for student in roster[schedule.teaching_class_id]:
                        audiences[schedule.id][student.id].append(str(day))
                        if timing is not None:
                            timed_audiences[schedule.id][timing][student.id].append(str(day))
            day += timedelta(days=1)
        entries = []
        for schedule, teaching, course in schedules:
            if resolver:
                timings = list(timed_audiences[schedule.id])
                if not timings:
                    continue  # 本学期无实际课次（含学院停课），不制造个人显示课次。
                start, end = timings[0]
                complete = [(time(start // 60, start % 60), time(end // 60, end % 60))]
            else:
                complete = self._school_interval(periods, schedule)
            if any(pair[0] >= pair[1] for pair in complete) or any(
                left[1] > right[0] for left, right in zip(complete, complete[1:], strict=False)
            ):
                raise AppError(ErrorCode.VALIDATION_ERROR, "节次时间无效或重叠，不能发布", 422)
            if not weeks[schedule.id] or any(
                not 1 <= week <= semester.total_weeks for week in weeks[schedule.id]
            ):
                raise AppError(ErrorCode.VALIDATION_ERROR, "课表生效周次不完整，不能发布", 422)
            snapshot = {
                "source_schedule_id": str(schedule.id),
                "teaching_class_id": str(teaching.id),
                "college_id": str(self.scope.college_id),
                "course_name": course.course_name,
                "class_name": teaching.class_name,
                "teacher": schedule.teacher or teaching.teacher_name,
                "classroom": schedule.classroom,
                "weekday": schedule.weekday,
                "week_nos": weeks[schedule.id],
                "start_period": schedule.start_period,
                "end_period": schedule.end_period,
                "start_time": str(complete[0][0]),
                "end_time": str(complete[-1][1]),
            }
            if resolver:
                for (start, end), audience in timed_audiences[schedule.id].items():
                    entries.append(
                        (
                            {
                                **snapshot,
                                "start_time": str(time(start // 60, start % 60)),
                                "end_time": str(time(end // 60, end % 60)),
                            },
                            dict(audience),
                        )
                    )
            else:
                entries.append((snapshot, dict(audiences[schedule.id])))
        return context, entries

    @staticmethod
    def _school_interval(periods, schedule):
        relevant = [periods.get(p) for p in range(schedule.start_period, schedule.end_period + 1)]
        if not relevant or any(pair is None or None in pair for pair in relevant):
            raise AppError(ErrorCode.VALIDATION_ERROR, "课表缺少完整作息时间，不能发布", 422)
        return [pair for pair in relevant if pair is not None]


class MyAcademicSourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def bound_student(self, user_id: int):
        student = self.db.scalar(
            select(Student)
            .join(UserAccount, UserAccount.student_id == Student.id)
            .where(
                UserAccount.id == user_id,
                UserAccount.status == "ACTIVE",
                Student.status == "ACTIVE",
            )
            .execution_options(populate_existing=True)
        )
        if student is None:
            raise PermissionDeniedError("请先完成有效学生绑定")
        return student

    def latest_ids(self, semester_id: int):
        return (
            select(func.max(AcademicPublication.id))
            .where(AcademicPublication.semester_id == semester_id)
            .group_by(AcademicPublication.college_id)
        )

    def own_entries(self, student_id: int, semester_id: int):
        if self.db.scalar(select(Semester.id).where(Semester.id == semester_id)) is None:
            raise NotFoundError("学期不存在")
        latest = self.latest_ids(semester_id)
        own_college = (
            select(AdministrativeClass.college_id)
            .join(Student, Student.administrative_class_id == AdministrativeClass.id)
            .where(Student.id == student_id)
        )
        audience_ids = select(PublicationAudience.publication_id).where(
            PublicationAudience.student_id == student_id
        )
        publications = list(
            self.db.scalars(
                select(AcademicPublication)
                .where(
                    AcademicPublication.id.in_(latest),
                    or_(
                        AcademicPublication.id.in_(audience_ids),
                        AcademicPublication.college_id.in_(own_college),
                    ),
                )
                .order_by(AcademicPublication.college_id)
            )
        )
        entry_rows = list(
            self.db.execute(
                select(PublishedSchedule, PublishedScheduleStudent.occurrence_dates)
                .join(
                    PublishedScheduleStudent,
                    PublishedScheduleStudent.published_schedule_id == PublishedSchedule.id,
                )
                .where(
                    PublishedSchedule.publication_id.in_(latest),
                    PublishedScheduleStudent.student_id == student_id,
                )
                .order_by(PublishedSchedule.id)
            )
        )
        entries = [{**row.snapshot, "occurrence_dates": dates} for row, dates in entry_rows]
        exists = bool(publications)
        return publications, entries, exists

    def notices(self, student_id: int, params: PageParams):
        stmt = (
            select(AcademicPublication)
            .join(PublicationAudience, PublicationAudience.publication_id == AcademicPublication.id)
            .where(
                PublicationAudience.student_id == student_id, PublicationAudience.changed.is_(True)
            )
        )
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list(
            self.db.scalars(
                stmt.order_by(AcademicPublication.id.desc())
                .offset(params.offset)
                .limit(params.limit)
            )
        )
        return rows, total
