"""旧业务模型到排班器的批量适配。

这里保留现有节次/日历口径，不能把当前作息当成历史真实时间快照。
SQL 数量不随任务×候选组合增长；写入前仍由服务在日期锚点下复核。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.academic.calendar import resolve_teaching_day
from app.modules.academic.models import (
    CalendarOverride,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClassStudent,
    VolunteerQualification,
)
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.course_policy import is_physical_education
from app.modules.inspection.models import InspectionAssignment, InspectionTask, TaskRosterMember

from .location import building_cluster
from .models import Task, Volunteer

REASONS = {
    "COURSE_NOT_INSPECTABLE": "体育课不作为被查目标",
    "NOT_VOLUNTEER": "账号非启用志愿者",
    "NO_QUALIFICATION": "本学期无有效志愿者资格或学生身份已停用",
    "OWN_CLASS_CONFLICT": "与本人课表时段冲突",
    "SELF_CLASS_AVOID": "被查名单含本人行政班学生",
    "TASK_TIME_CONFLICT": "与已有或本轮查课任务时段冲突，有限修复未找到分配",
    "DAY_CAP_EXCEEDED": "超出单日受派上限",
    "WEEK_CAP_EXCEEDED": "超出每周受派上限",
}


@dataclass
class Snapshot:
    tasks: list[Task]
    volunteers: list[Volunteer]
    static_failures: dict[int, str]


def load_snapshot(
    session: Session, semester: Semester, targets: list[InspectionTask], candidate_ids: list[int],
    *, lock_inputs: bool = False,
) -> Snapshot:
    if not targets:
        return Snapshot([], [], {})
    ids = sorted(set(candidate_ids))
    settings = get_settings()

    def read(statement):
        # 提交前使用当前锁定读，不能复用鉴权时已经建立的 RR 一致性快照。
        if lock_inputs:
            statement = statement.with_for_update(read=True).execution_options(
                populate_existing=True)
        return session.execute(statement)

    dates = {t.inspection_date for t in targets}
    overrides = {row.date: row for row in read(
        select(CalendarOverride).where(CalendarOverride.semester_id == semester.id,
                                       CalendarOverride.date.in_(dates))
    ).scalars()}
    teaching_days = {day: resolve_teaching_day(semester.first_monday, day, overrides.get(day))
                     for day in dates}
    weeks = {value[0] for value in teaching_days.values() if value is not None}
    weekdays = {value[1] for value in teaching_days.values() if value is not None}
    occupied_dates = dates
    if settings.assignment_max_tasks_per_week:
        occupied_dates = {day - timedelta(days=day.weekday()) + timedelta(days=i)
                          for day in dates for i in range(7)}
    profiles = {row.id: row for row in read(
        select(UserAccount.id, UserAccount.status, UserAccount.student_id,
               Student.administrative_class_id, Student.status.label("student_status"))
        .outerjoin(Student, Student.id == UserAccount.student_id)
        .where(UserAccount.id.in_(ids))
    )}
    roles = set(read(
        select(UserRole.user_id).join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(ids), Role.code == "VOLUNTEER")
    ).scalars())
    student_ids = [p.student_id for p in profiles.values() if p.student_id is not None]
    qualified = set(read(
        select(VolunteerQualification.student_id).where(
            VolunteerQualification.semester_id == semester.id,
            VolunteerQualification.student_id.in_(student_ids),
            VolunteerQualification.enabled.is_(True),
        )
    ).scalars())
    roster_classes = defaultdict(set)
    for tid, cid in read(
        select(TaskRosterMember.task_id, Student.administrative_class_id)
        .join(Student, Student.id == TaskRosterMember.student_id)
        .join(InspectionTask, InspectionTask.id == TaskRosterMember.task_id)
        .where(InspectionTask.id.in_([t.id for t in targets]),
               TaskRosterMember.roster_version == InspectionTask.roster_version)
    ):
        if cid is not None:
            roster_classes[tid].add(cid)
    courses = defaultdict(list)
    for sid, weekday, week, start, end in read(
        select(TeachingClassStudent.student_id, CourseSchedule.weekday,
               CourseScheduleWeek.week_no, CourseSchedule.start_period, CourseSchedule.end_period)
        .join(TeachingClassStudent,
              TeachingClassStudent.teaching_class_id == CourseSchedule.teaching_class_id)
        .join(CourseScheduleWeek, CourseScheduleWeek.schedule_id == CourseSchedule.id)
        .where(TeachingClassStudent.student_id.in_(student_ids),
               CourseSchedule.semester_id == semester.id, CourseSchedule.status == "ACTIVE",
               CourseScheduleWeek.week_no.in_(weeks), CourseSchedule.weekday.in_(weekdays))
    ):
        courses[sid, weekday, week].append((start, end))
    loads = {vid: count for vid, count in session.execute(
        select(InspectionAssignment.volunteer_user_id, func.count())
        .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
        .where(InspectionTask.semester_id == semester.id, InspectionTask.canceled_at.is_(None),
               InspectionAssignment.revoked_at.is_(None),
               InspectionAssignment.volunteer_user_id.in_(ids))
        .group_by(InspectionAssignment.volunteer_user_id)
    )}
    period_times = {row.period_no: (row.start_time, row.end_time) for row in read(
        select(PeriodDefinition.period_no, PeriodDefinition.start_time, PeriodDefinition.end_time)
        .where(PeriodDefinition.semester_id == semester.id)
    )}

    def convert(task: InspectionTask, candidates: frozenset[int]) -> Task:
        periods = [period_times.get(p) for p in range(task.start_period, task.end_period + 1)]
        parts: set[str] = set()
        minutes = None
        if periods and all(pair and pair[0] and pair[1] for pair in periods):
            complete = [pair for pair in periods if pair is not None]
            first, last = complete[0][0], complete[-1][1]
            start, end = first.hour * 60 + first.minute, last.hour * 60 + last.minute
            if start < end:
                minutes = (start, end)
                for name, low, high in [("MORNING", 0, 720), ("AFTERNOON", 720, 1080),
                                        ("EVENING", 1080, 1440)]:
                    if start < high and low < end:
                        parts.add(name)
        return Task(task.id, task.inspection_date, task.start_period, task.end_period + 1,
                    candidates, frozenset(parts),
                    cluster=building_cluster(task.classroom_snapshot,
                                             settings.assignment_building_clusters),
                    minutes=minutes)

    existing = defaultdict(list)
    for vid, task in read(
        select(InspectionAssignment.volunteer_user_id, InspectionTask)
        .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
        .where(InspectionAssignment.volunteer_user_id.in_(ids),
               InspectionAssignment.revoked_at.is_(None),
               InspectionTask.inspection_date.in_(occupied_dates),
               InspectionTask.canceled_at.is_(None))
    ):
        # 跨学期受派也占用时间，但不能用当前学期作息解释其他学期的时段。
        if task.semester_id == semester.id:
            existing[vid].append(convert(task, frozenset()))
        else:
            existing[vid].append(Task(task.id, task.inspection_date, task.start_period,
                                      task.end_period + 1, frozenset()))
    tasks, failures = [], {}
    for task in targets:
        if (task.inspection_type == "COURSE"
                and is_physical_education(task.course_name_snapshot)):
            tasks.append(convert(task, frozenset()))
            failures[task.id] = "COURSE_NOT_INSPECTABLE"
            continue
        candidates, rejected = set(), []
        teaching = teaching_days[task.inspection_date]
        week, weekday = teaching if teaching is not None else (0, 0)
        for vid in ids:
            prof = profiles.get(vid)
            reason = None
            if prof is None or prof.status != "ACTIVE" or vid not in roles:
                reason = "NOT_VOLUNTEER"
            elif prof.student_status != "ACTIVE" or prof.student_id not in qualified:
                reason = "NO_QUALIFICATION"
            elif any(task.start_period <= end and start <= task.end_period
                     for start, end in courses[prof.student_id, weekday, week]):
                reason = "OWN_CLASS_CONFLICT"
            elif prof.administrative_class_id in roster_classes[task.id]:
                reason = "SELF_CLASS_AVOID"
            if reason:
                rejected.append(reason)
            else:
                candidates.add(vid)
        if not candidates:
            failures[task.id] = rejected[0] if rejected else "NO_QUALIFICATION"
        tasks.append(convert(task, frozenset(candidates)))
    return Snapshot(tasks, [Volunteer(v, loads.get(v, 0), tuple(existing[v])) for v in ids],
                    failures)
