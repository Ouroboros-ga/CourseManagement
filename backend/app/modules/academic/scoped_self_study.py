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


def create_self_study(service, body):
    service._repo("academic.manage", write=True)
    service._repo("student.manage", write=True)
    semester = service._semester(body.semester_id)

    if body.start_period > body.end_period:
        raise ConflictError(message="节次范围无效：结束节次不能小于开始节次")

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
                CourseType.name.like(f"%{type_name}%"),
            )
        )
        if ctype:
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

    classes_created = 0
    schedules_created = 0
    students_linked = 0

    weeks_set = sorted(set(body.weeks))
    weekdays_set = sorted(set(body.weekdays))

    for ac in admin_classes:
        tc_code = f"SS_{body.study_type}_{ac.class_code}"
        tc_name = f"{ac.class_name}{type_name}"

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
            )
            service.db.add(teaching)
            service.db.flush()
            classes_created += 1
        elif course_type_id and not teaching.course_type_id:
            teaching.course_type_id = course_type_id

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
                service.db.add(
                    TeachingClassStudent(teaching_class_id=teaching.id, student_id=s.id)
                )
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
                    CourseSchedule.start_period == body.start_period,
                    CourseSchedule.end_period == body.end_period,
                    CourseSchedule.college_id == service.college_id,
                )
                .with_for_update()
            )
            if schedule is None:
                schedule = CourseSchedule(
                    semester_id=semester.id,
                    teaching_class_id=teaching.id,
                    weekday=wd,
                    start_period=body.start_period,
                    end_period=body.end_period,
                    classroom=classroom,
                    college_id=service.college_id,
                    status="ACTIVE",
                )
                service.db.add(schedule)
                service.db.flush()
                schedules_created += 1
            elif classroom and not schedule.classroom:
                schedule.classroom = classroom

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

    return {
        "status": "SUCCESS",
        "study_type": body.study_type,
        "classes_count": len(admin_classes),
        "classes_created": classes_created,
        "schedules_created": schedules_created,
        "students_linked": students_linked,
    }
