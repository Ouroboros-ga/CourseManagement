"""College master timetable, with dated official rosters rather than personal copies."""

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import raiseload, selectinload

from app.core.exceptions import ConflictError
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    TeachingClass,
)
from app.modules.academic.roster_index import RosterIndex
from app.modules.academic.schemas import MasterTimetableItemResponse
from app.modules.identity.role_scope import business_today
from app.modules.inspection.course_policy import is_physical_education


def master_timetable(
    service,
    semester_id,
    *,
    week_no=None,
    weekday=None,
    administrative_class_id=None,
    keyword=None,
    params=None,
):
    repo = service._repo("academic.read")
    semester = repo.get("semesters", semester_id)
    statement = (
        select(CourseSchedule, TeachingClass, Course)
        .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
        .join(Course, Course.id == TeachingClass.course_id)
        .options(selectinload(CourseSchedule.weeks), raiseload("*"))
        .where(
            CourseSchedule.college_id == service.college_id,
            TeachingClass.college_id == service.college_id,
            or_(Course.college_id.is_(None), Course.college_id == service.college_id),
            CourseSchedule.semester_id == semester.id,
            TeachingClass.semester_id == semester.id,
            CourseSchedule.status == "ACTIVE",
            TeachingClass.status == "ACTIVE",
            Course.status == "ACTIVE",
        )
    )
    if weekday is not None:
        statement = statement.where(CourseSchedule.weekday == weekday)
    if keyword:
        statement = statement.where(
            or_(
                Course.course_name.contains(keyword, autoescape=True),
                TeachingClass.class_name.contains(keyword, autoescape=True),
            )
        )
    if week_no is not None:
        statement = statement.where(CourseSchedule.weeks.any(CourseScheduleWeek.week_no == week_no))
    statement = statement.order_by(
        CourseSchedule.weekday, CourseSchedule.start_period, CourseSchedule.id
    )
    # 行政班筛选必须使用下方日期名单，不能用当前班级替代历史归属。
    sql_paged = params is not None and administrative_class_id is None
    total = (
        int(
            service.db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        )
        if sql_paged
        else 0
    )
    if sql_paged:
        statement = statement.limit(params.limit).offset(params.offset)
    rows = list(service.db.execute(statement))
    index = RosterIndex(service.db, [teaching.id for _, teaching, _ in rows])
    classes = {
        row.id: row
        for row in service.db.scalars(
            select(AdministrativeClass).where(AdministrativeClass.college_id == service.college_id)
        )
    }
    roster_cache = {}
    roster_details_cache = {}
    result = []
    for schedule, teaching, course in rows:
        weeks = sorted(row.week_no for row in schedule.weeks)
        if week_no is not None and week_no not in weeks:
            continue
        day = (
            semester.first_monday + timedelta(days=(week_no - 1) * 7 + schedule.weekday - 1)
            if week_no
            else min(max(business_today(), semester.start_date), semester.end_date)
        )
        cache_key = (teaching.id, day)
        if cache_key not in roster_details_cache:
            if day not in roster_cache:
                roster_cache[day] = index.at(day)
            roster = roster_cache[day].get(teaching.id, [])
            if not roster:
                # 当日因学籍迁移基线生效日期等未核实情况导致正式名单为空时，
                # 回退使用迁移前投影名单，消除排课与课表界面的历史断崖。
                roster = index.for_personal_timetable(day).get(teaching.id, [])
            class_ids = set()
            for student in roster:
                enrollment = index.enrollment_at(student.id, day)
                class_id = (
                    enrollment.administrative_class_id
                    if enrollment
                    else student.administrative_class_id
                )
                if class_id not in classes or (
                    enrollment and enrollment.college_id != service.college_id
                ):
                    raise ConflictError(message="正式名单包含未核实或外院归属，请先处理教务名单")
                class_ids.add(class_id)
            details = [classes[cid] for cid in sorted(class_ids)]
            teachers = (
                "、".join(dict.fromkeys(row.head_teacher for row in details if row.head_teacher))
                or None
            )
            counselors = (
                "、".join(dict.fromkeys(row.counselor for row in details if row.counselor)) or None
            )
            roster_details_cache[cache_key] = (roster, class_ids, details, teachers, counselors)
        roster, class_ids, details, teachers, counselors = roster_details_cache[cache_key]
        if administrative_class_id is not None and administrative_class_id not in class_ids:
            continue
        physical = is_physical_education(course.course_name)
        item = MasterTimetableItemResponse(
            id=schedule.id,
            semester_id=semester.id,
            course_id=course.id,
            course_code=course.course_code,
            course_name=course.course_name,
            teaching_class_id=teaching.id,
            teaching_class_code=teaching.class_code,
            teaching_class_name=teaching.class_name,
            teacher_name=schedule.teacher or teaching.teacher_name or None,
            head_teacher=teachers,
            counselor=counselors,
            weekday=schedule.weekday,
            start_period=schedule.start_period,
            end_period=schedule.end_period,
            classroom=schedule.classroom,
            weeks=weeks,
            status=schedule.status,
            enrolled_student_count=len(roster),
            is_physical_education=physical,
            is_inspectable=not physical and bool(roster),
            administrative_classes=[row.class_name for row in details],
            administrative_classes_details=[
                {
                    "class_name": row.class_name,
                    "head_teacher": row.head_teacher,
                    "counselor": row.counselor,
                }
                for row in details
            ],
        ).model_dump()
        item.update(
            ownership_version=schedule.ownership_version,
            teaching_class_ownership_version=teaching.ownership_version,
            classification_revision=teaching.classification_revision,
            course_type_id=str(teaching.course_type_id) if teaching.course_type_id else None,
        )
        result.append(item)
    result.sort(key=lambda row: (row["weekday"], row["start_period"], row["course_name"]))
    if not sql_paged:
        total = len(result)
        if params is not None:
            result = result[params.offset : params.offset + params.limit]
    return {
        "items": result,
        "total": total,
        **({"page": params.page, "page_size": params.page_size} if params is not None else {}),
    }
