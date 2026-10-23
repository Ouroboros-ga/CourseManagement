"""院级早自习与晚自习批量生成；事务原子落库，自动关联行政班在籍学生。"""

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Student,
    TeachingClass,
    TeachingClassStudent,
)
from app.modules.academic.self_study_time import clock_profile
from app.modules.academic.time_service import TimeResolver


def create_self_study(service, body):
    service._repo("academic.manage", write=True)
    service._repo("student.manage", write=True)
    semester = service._semester(body.semester_id)
    from app.core.config import get_settings

    if body.start_time is not None and not get_settings().campus_scheduling_enabled:
        raise ConflictError(message="独立自习时段需要启用实际时间排班链路")

    if body.start_period is not None and body.start_period > body.end_period:
        raise ConflictError(message="节次范围无效：结束节次不能小于开始节次")

    weeks_set = service._weeks(semester, body.weeks)

    type_name = "早自习" if body.study_type == "EARLY" else "晚自习"

    # 解析课程类型（若存在当前学院的对应类型则绑定）
    course_type_id = None
    if body.course_type_id:
        ctype = service.db.scalar(
            select(CourseType).where(
                CourseType.id == body.course_type_id,
                CourseType.college_id == service.college_id,
                CourseType.status == "ACTIVE",
            )
        )
        if ctype is None:
            raise NotFoundError("指定的课程类型不存在或非本院有效类型")
        course_type_id = ctype.id
    else:
        ctype = service.db.scalar(
            select(CourseType).where(
                CourseType.college_id == service.college_id,
                CourseType.status == "ACTIVE",
                CourseType.builtin_key
                == ("morning_study" if body.study_type == "EARLY" else "evening_study"),
            )
        )
        if ctype is None:
            raise ConflictError(message="自习课程类型不存在或已停用，请先维护课程类型")
        course_type_id = ctype.id

    # 查找或创建学院统一自习课程
    course_code = f"SS_{body.study_type}_{service.college_id}"
    course = service.db.scalar(
        select(Course)
        .where(Course.course_code == course_code, Course.college_id == service.college_id)
        .with_for_update()
    )
    if course is None:
        course = Course(
            course_code=course_code, course_name=type_name, college_id=service.college_id
        )
        service.db.add(course)
        service.db.flush()

    # 校验行政班归属
    admin_classes = list(
        service.db.scalars(
            select(AdministrativeClass).where(
                AdministrativeClass.id.in_(body.class_ids),
                AdministrativeClass.college_id == service.college_id,
            )
        )
    )
    if len(admin_classes) != len(set(body.class_ids)):
        raise NotFoundError("名单包含不存在或非本院行政班，整批未生成")
    if any(ac.status != "ACTIVE" for ac in admin_classes):
        raise ConflictError(message="名单包含停用行政班，整批未生成")

    profile = clock_profile(service, semester, body)
    start_period = 1 if profile else body.start_period
    end_period = 1 if profile else body.end_period

    classes_created = 0
    schedules_created = 0
    students_linked = 0

    weekdays_set = sorted(set(body.weekdays))

    for ac in admin_classes:
        base_code = f"SS_{body.study_type}_{ac.class_code}"
        # 每个实际时段有独立教学班，不能重绑旧班而改变已有排课和任务。
        suffix = f"_{body.start_time:%H%M}_{body.end_time:%H%M}" if profile else ""
        tc_code = base_code + suffix
        if len(tc_code) > 64:
            import hashlib

            key = hashlib.sha256(base_code.encode()).hexdigest()[:24]
            tc_code = f"SS_{body.study_type}_{key}{suffix}"
        tc_name = f"{ac.class_name}{type_name}"

        if profile:
            competing = service.db.scalar(
                select(CourseSchedule.id)
                .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
                .join(CourseScheduleWeek, CourseScheduleWeek.schedule_id == CourseSchedule.id)
                .where(
                    TeachingClass.college_id == service.college_id,
                    TeachingClass.semester_id == semester.id,
                    TeachingClass.course_id == course.id,
                    TeachingClass.class_code.in_([base_code, tc_code])
                    | TeachingClass.class_code.startswith(base_code + "_", autoescape=True)
                    | TeachingClass.id.in_(
                        select(TeachingClassStudent.teaching_class_id)
                        .join(Student, Student.id == TeachingClassStudent.student_id)
                        .where(Student.administrative_class_id == ac.id)
                    ),
                    TeachingClass.time_profile_id.is_distinct_from(profile.id),
                    TeachingClass.status == "ACTIVE",
                    CourseSchedule.status == "ACTIVE",
                    CourseSchedule.weekday.in_(weekdays_set),
                    CourseScheduleWeek.week_no.in_(weeks_set),
                )
                .limit(1)
            )
            if competing is not None:
                raise ConflictError(
                    message="所选班级、星期和周次已有自习使用其他时间；请先在正式课表处置未来排期，再重新生成"
                )

        teaching = service.db.scalar(
            select(TeachingClass)
            .where(
                TeachingClass.college_id == service.college_id,
                TeachingClass.semester_id == semester.id,
                TeachingClass.course_id == course.id,
                TeachingClass.class_code == tc_code,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if teaching is None:
            teaching = TeachingClass(
                college_id=service.college_id,
                semester_id=semester.id,
                course_id=course.id,
                course_type_id=course_type_id,
                class_code=tc_code,
                class_name=tc_name,
                teacher_name=body.teacher_name,
                status="ACTIVE",
                time_profile_id=profile.id if profile else None,
            )
            service.db.add(teaching)
            service.db.flush()
            classes_created += 1
        elif course_type_id and not teaching.course_type_id:
            teaching.course_type_id = course_type_id
        if teaching.status != "ACTIVE" or teaching.course_type_id != course_type_id:
            raise ConflictError(message="已有自习教学班停用或类型不一致，请先核对正式课表")
        if profile and teaching.time_profile_id != profile.id:
            raise ConflictError(message="已有自习教学班的时段绑定已变更，请先核对正式课表")

        # 关联行政班在籍有效学生
        students = list(
            service.db.scalars(
                select(Student).where(
                    Student.administrative_class_id == ac.id,
                    Student.status == "ACTIVE",
                )
            )
        )
        existing_sids = set(
            service.db.scalars(
                select(TeachingClassStudent.student_id).where(
                    TeachingClassStudent.teaching_class_id == teaching.id
                )
            )
        )
        for s in students:
            if s.id not in existing_sids:
                service.db.add(TeachingClassStudent(teaching_class_id=teaching.id, student_id=s.id))
                existing_sids.add(s.id)
                students_linked += 1

        # 排课时段与周次展开
        classroom = (
            body.classrooms.get(str(ac.id))
            or body.classrooms.get(ac.class_code)
            or body.default_classroom
            or ""
        )
        for wd in weekdays_set:
            schedule = service.db.scalar(
                select(CourseSchedule)
                .where(
                    CourseSchedule.semester_id == semester.id,
                    CourseSchedule.teaching_class_id == teaching.id,
                    CourseSchedule.weekday == wd,
                    CourseSchedule.start_period == start_period,
                    CourseSchedule.end_period == end_period,
                    CourseSchedule.college_id == service.college_id,
                )
                .with_for_update()
            )
            if schedule is None:
                schedule = CourseSchedule(
                    semester_id=semester.id,
                    teaching_class_id=teaching.id,
                    weekday=wd,
                    start_period=start_period,
                    end_period=end_period,
                    classroom=classroom,
                    college_id=service.college_id,
                    status="ACTIVE",
                )
                service.db.add(schedule)
                service.db.flush()
                schedules_created += 1
            elif classroom and not schedule.classroom:
                schedule.classroom = classroom
            elif schedule.status != "ACTIVE" or (classroom and schedule.classroom != classroom):
                raise ConflictError(message="已有自习排期停用或教室不一致，请在正式课表明确修改")

            service._schedule_time(schedule, semester, weeks_set, resolver=TimeResolver(service.db))

            existing_weeks = set(
                service.db.scalars(
                    select(CourseScheduleWeek.week_no).where(
                        CourseScheduleWeek.schedule_id == schedule.id
                    )
                )
            )
            for w in weeks_set:
                if w not in existing_weeks:
                    service.db.add(CourseScheduleWeek(schedule_id=schedule.id, week_no=w))
                    existing_weeks.add(w)

    result = {
        "status": "SUCCESS",
        "study_type": body.study_type,
        "classes_count": len(admin_classes),
        "classes_created": classes_created,
        "schedules_created": schedules_created,
        "students_linked": students_linked,
        "time_basis": "CLOCK" if profile else "PERIODS",
        "time_label": f"{body.start_time:%H:%M}—{body.end_time:%H:%M}" if profile else None,
        "time_profile_id": str(profile.id) if profile else None,
    }
    service.db.flush()
    service._audit(
        "academic.course.batch_self_study_create",
        course,
        None,
        body.reason,
        after_extra={"batch_result": result},
    )
    return result
