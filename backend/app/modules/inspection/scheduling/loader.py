"""旧业务模型到排班器的批量适配。

这里保留现有节次/日历口径，不能把当前作息当成历史真实时间快照。
SQL 数量不随任务×候选组合增长；写入前仍由服务在日期锚点下复核。
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.academic.calendar import resolve_teaching_day
from app.modules.academic.models import (
    CalendarOverride,
    PeriodDefinition,
    Semester,
    Student,
    VolunteerQualification,
)
from app.modules.academic.qualification_policy import qualified_on
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.course_policy import is_physical_education
from app.modules.inspection.models import InspectionTask, TaskRosterMember

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
    warnings: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    input_revision: str = ""


def load_snapshot(
    session: Session,
    semester: Semester,
    targets: list[InspectionTask],
    candidate_ids: list[int],
    *,
    lock_inputs: bool = False,
) -> Snapshot:
    if not targets:
        return Snapshot([], [], {})
    ids = sorted(set(candidate_ids))
    settings = get_settings()

    def read(statement):
        # 提交前使用当前锁定读，不能复用鉴权时已经建立的 RR 一致性快照。
        if lock_inputs:
            statement = statement.with_for_update(read=True).execution_options(
                populate_existing=True
            )
        return session.execute(statement)

    dates = {t.inspection_date for t in targets}
    overrides = {
        row.date: row
        for row in read(
            select(CalendarOverride).where(
                CalendarOverride.semester_id == semester.id, CalendarOverride.date.in_(dates)
            )
        ).scalars()
    }
    teaching_days = {
        day: resolve_teaching_day(semester.first_monday, day, overrides.get(day)) for day in dates
    }
    occupied_dates = dates
    if settings.assignment_max_tasks_per_week or settings.campus_scheduling_enabled:
        occupied_dates = {
            day - timedelta(days=day.weekday()) + timedelta(days=i)
            for day in dates
            for i in range(7)
        }
    profiles = {
        row.id: row
        for row in read(
            select(
                UserAccount.id,
                UserAccount.status,
                UserAccount.student_id,
                Student.administrative_class_id,
                Student.status.label("student_status"),
            )
            .outerjoin(Student, Student.id == UserAccount.student_id)
            .where(UserAccount.id.in_(ids))
        )
    }
    roles = set(
        read(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(ids), Role.code == "VOLUNTEER")
        ).scalars()
    )
    student_ids = [p.student_id for p in profiles.values() if p.student_id is not None]
    qualified = {
        row.student_id: row
        for row in read(
            select(VolunteerQualification).where(
                VolunteerQualification.semester_id == semester.id,
                VolunteerQualification.student_id.in_(student_ids),
                VolunteerQualification.enabled.is_(True),
            )
        ).scalars()
    }
    roster_classes = defaultdict(set)
    for tid, cid in read(
        select(TaskRosterMember.task_id, TaskRosterMember.administrative_class_id_snapshot)
        .join(InspectionTask, InspectionTask.id == TaskRosterMember.task_id)
        .where(
            InspectionTask.id.in_([t.id for t in targets]),
            TaskRosterMember.roster_version == InspectionTask.roster_version,
        )
    ):
        if cid is not None:
            roster_classes[tid].add(cid)
    from app.modules.academic.enrollment_service import EnrollmentService
    from app.modules.inspection.scheduling.private_constraints import (
        assignment_loads,
        assignment_times,
        course_times,
    )

    enrollments = EnrollmentService(session)
    from app.modules.volunteer.eligibility_index import EligibilityIndex
    eligibility = EligibilityIndex(session, student_ids, targets, lock=lock_inputs) if settings.campus_scheduling_enabled else None
    courses = defaultdict(list, {} if eligibility else course_times(session, semester.id, student_ids, teaching_days))
    loads = assignment_loads(session, semester.id, ids)
    if settings.campus_scheduling_enabled:
        from app.modules.inspection.formal_time import formal_course_slots

        actual_slots = formal_course_slots(session, set(student_ids), dates, lock=lock_inputs)
        courses = defaultdict(list, {
            key: [(start, end) for start, end, *_ in slots]
            for key, slots in actual_slots.items()
        })
    period_times = {row.period_no: (row.start_time, row.end_time) for row in read(
        select(PeriodDefinition.period_no, PeriodDefinition.start_time, PeriodDefinition.end_time)
        .where(PeriodDefinition.semester_id == semester.id)
    )}

    rules_cache: dict[int, Any] = {}
    conversions: dict[int, Task] = {}

    def convert(task: InspectionTask, candidates: frozenset[int]) -> Task:
        if task.id in conversions:
            return replace(conversions[task.id], candidates=candidates)
        if settings.campus_scheduling_enabled:
            from app.modules.volunteer.rules import assignment_interval

            start, end = assignment_interval(session, task)
            actual_parts = frozenset(name for name, low, high in [
                ("MORNING", 0, 720), ("AFTERNOON", 720, 1080), ("EVENING", 1080, 1440)
            ] if start < high and low < end)
            from app.modules.volunteer.models import GroupConfigVersion
            version = session.get(GroupConfigVersion, task.group_config_version_id) if task.group_config_version_id else None
            # 已有受派即使组已停用仍占用其冻结配额，不能按当前组配置重解释。
            config = rules_cache[task.id].config if task.id in rules_cache else (
                version.configuration if version and version.group_id == task.group_id
                and version.college_id == task.college_id else {})
            result = Task(task.id, task.inspection_date, start, end, frozenset(), actual_parts,
                cluster=building_cluster(task.classroom_snapshot, settings.assignment_building_clusters),
                minutes=(start, end), group_id=task.group_id,
                group_daily_limit=config.get("daily_limit"),
                group_weekly_limit=config.get("weekly_limit"),
                count_all_groups=config.get("count_scope", "ALL_GROUPS") == "ALL_GROUPS")
            conversions[task.id] = result
            return replace(result, candidates=candidates)
        periods = [period_times.get(p) for p in range(task.start_period, task.end_period + 1)]
        parts: set[str] = set()
        minutes = None
        if periods and all(pair and pair[0] and pair[1] for pair in periods):
            complete = [pair for pair in periods if pair is not None]
            first, last = complete[0][0], complete[-1][1]
            start, end = first.hour * 60 + first.minute, last.hour * 60 + last.minute
            if start < end:
                minutes = (start, end)
                for name, low, high in [
                    ("MORNING", 0, 720),
                    ("AFTERNOON", 720, 1080),
                    ("EVENING", 1080, 1440),
                ]:
                    if start < high and low < end:
                        parts.add(name)
        return Task(
            task.id,
            task.inspection_date,
            task.start_period,
            task.end_period + 1,
            candidates,
            frozenset(parts),
            cluster=building_cluster(
                task.classroom_snapshot, settings.assignment_building_clusters
            ),
            minutes=minutes,
        )

    existing = defaultdict(list)
    for vid, task in assignment_times(session, ids, occupied_dates, lock=lock_inputs):
        if task.id in {target.id for target in targets}:
            continue
        # 跨学期受派也占用时间，但不能用当前学期作息解释其他学期的时段。
        if settings.campus_scheduling_enabled or task.semester_id == semester.id:
            existing[vid].append(convert(task, frozenset()))
        else:
            existing[vid].append(
                Task(
                    task.id,
                    task.inspection_date,
                    task.start_period,
                    task.end_period + 1,
                    frozenset(),
                )
            )
    tasks, failures, warnings = [], {}, {}
    for task in targets:
        group_rules = None
        if settings.campus_scheduling_enabled and task.group_id:
            from app.modules.volunteer.rules import GroupRules

            group_rules = GroupRules(session, task)
            rules_cache[task.id] = group_rules
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
            enrollment = (
                eligibility.enrollment(prof.student_id, task.inspection_date) if eligibility and prof and prof.student_id else
                enrollments.at(prof.student_id, task.inspection_date, lock=lock_inputs)
                if prof and prof.student_id
                else None
            )
            enrolled = (
                enrollment.status == "ENROLLED"
                if enrollment
                else prof is not None and prof.student_status == "ACTIVE"
            )
            class_id = (
                eligibility.class_id(prof.student_id, task.inspection_date) if eligibility and prof else
                enrollment.administrative_class_id
                if enrollment
                else prof.administrative_class_id
                if prof
                else None
            )
            reason = None
            if prof is None or prof.status != "ACTIVE" or vid not in roles:
                reason = "NOT_VOLUNTEER"
            elif group_rules and eligibility and not eligibility.member_allowed(task, prof.student_id):
                reason = "NO_QUALIFICATION"
            elif not enrolled or not (eligibility.qualified(qualified.get(prof.student_id), task.inspection_date, None if group_rules else task.college_id)
                    if eligibility else qualified_on(session, qualified.get(prof.student_id), task.inspection_date, None if group_rules else task.college_id)):
                reason = "NO_QUALIFICATION"
            elif group_rules and any(
                    convert(task, frozenset()).start < end and start < convert(task, frozenset()).end
                    and group_rules.course_effect(tid, ctype) == "BLOCK"
                    for start, end, tid, ctype in actual_slots[prof.student_id, task.inspection_date]):
                reason = "OWN_CLASS_CONFLICT"
            elif not group_rules and any((convert(task, frozenset()).start < end and start < convert(task, frozenset()).end)
                     if settings.campus_scheduling_enabled
                     else (task.start_period <= end and start <= task.end_period)
                     for start, end in courses[prof.student_id, task.inspection_date]):
                reason = "OWN_CLASS_CONFLICT"
            elif class_id in roster_classes[task.id] and (group_rules is None or group_rules.config["own_class_effect"] == "BLOCK"):
                reason = "SELF_CLASS_AVOID"
            if reason:
                rejected.append(reason)
            else:
                candidates.add(vid)
                if group_rules and prof:
                    from app.modules.volunteer.policy import assignment_warning_codes
                    warnings[task.id, vid] = assignment_warning_codes(group_rules.config,
                        class_id, roster_classes[task.id],
                        (convert(task, frozenset()).start, convert(task, frozenset()).end),
                        actual_slots[prof.student_id, task.inspection_date])
        if not candidates:
            failures[task.id] = rejected[0] if rejected else "NO_QUALIFICATION"
        tasks.append(convert(task, frozenset(candidates)))
    from app.modules.inspection.assignment_fingerprint import fingerprint

    inputs = {"courses": actual_slots if settings.campus_scheduling_enabled else courses}
    if eligibility:
        # Include dated membership/support/academic changes even when eligibility
        # still yields the same warning, so an old confirmation cannot be reused.
        for name in ("timelines", "members", "supports"):
            inputs[name] = {
                sid: [
                    {column.name: getattr(row, column.name) for column in row.__table__.columns}
                    for row in sorted(rows, key=lambda row: row.id)
                ] for sid, rows in getattr(eligibility, name).items()
            }
    return Snapshot(
        tasks, [Volunteer(v, loads.get(v, 0), tuple(existing[v])) for v in ids], failures, warnings,
        fingerprint(inputs),
    )
