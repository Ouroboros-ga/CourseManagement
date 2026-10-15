"""院级批量新建；重复相同内容幂等，既有资料变更必须走带版本编辑。"""

import hashlib

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Student,
    TeachingClass,
    TeachingClassStudent,
)


def create(service, body):
    service._repo("academic.manage", write=True)
    students_repo = service._repo("student.manage", write=True)
    semester = service._semester(body.semester_id)
    prepared = []
    codes = set()
    for item in body.teaching_classes:
        code = item.class_code.strip()
        if not code or code in codes or item.start_period > item.end_period:
            raise ConflictError(message="教学班编码重复、为空或节次范围无效")
        codes.add(code)
        requested = {number.strip() for number in item.student_nos}
        students = list(
            service.db.scalars(
                students_repo.query("students")
                .where(Student.student_no.in_(requested))
                .with_for_update()
            )
        )
        if {s.student_no for s in students} != requested or any(
            service._dto(s)["status"] != "ACTIVE" for s in students
        ):
            raise NotFoundError("名单包含未知、停用或外院学生，整批未录入")
        prepared.append(
            (item, service._weeks(semester, item.weeks), sorted(s.id for s in students))
        )
    name = body.course_name.strip()
    course_code = (
        body.course_code
        or f"C_{service.college_id}_{hashlib.sha256(name.encode()).hexdigest()[:16]}"
    ).strip()
    course = service.db.scalar(
        select(Course).where(Course.course_code == course_code, Course.college_id == service.college_id).with_for_update()
    )
    if course and (course.college_id != service.college_id or course.course_name != name):
        raise ConflictError(message="课程编码不可用于本次新建，请使用学院独立编码")
    if course is None:
        course = Course(course_code=course_code, course_name=name, college_id=service.college_id)
        service.db.add(course)
        service.db.flush()
    teaching_count, schedule_count, student_count = 0, 0, 0
    for item, weeks, students in prepared:
        teaching = service.db.scalar(
            select(TeachingClass)
            .where(
                TeachingClass.college_id == service.college_id,
                TeachingClass.semester_id == semester.id,
                TeachingClass.course_id == course.id,
                TeachingClass.class_code == item.class_code.strip(),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        class_name = (item.class_name or f"{name}-{item.class_code.strip()}").strip()
        if teaching:
            roster = sorted(
                service.db.scalars(
                    select(TeachingClassStudent.student_id).where(
                        TeachingClassStudent.teaching_class_id == teaching.id
                    )
                )
            )
            schedules = list(
                service.db.scalars(
                    select(CourseSchedule).where(
                        CourseSchedule.teaching_class_id == teaching.id,
                        CourseSchedule.college_id == service.college_id,
                    )
                )
            )
            match = False
            for schedule in schedules:
                existing_weeks = sorted(
                    service.db.scalars(
                        select(CourseScheduleWeek.week_no).where(
                            CourseScheduleWeek.schedule_id == schedule.id
                        )
                    )
                )
                match |= (
                    schedule.weekday,
                    schedule.start_period,
                    schedule.end_period,
                    schedule.classroom or "",
                    existing_weeks,
                ) == (item.weekday, item.start_period, item.end_period, item.classroom or "", weeks)
            if (
                teaching.class_name != class_name
                or teaching.status != "ACTIVE"
                or roster != students
                or not match
            ):
                raise ConflictError(
                    message="教学班已存在且内容不同，请使用带版本的编辑入口；整批未录入"
                )
            continue
        teaching = TeachingClass(
            semester_id=semester.id,
            course_id=course.id,
            college_id=service.college_id,
            class_code=item.class_code.strip(),
            class_name=class_name,
        )
        service.db.add(teaching)
        service.db.flush()
        schedule = CourseSchedule(
            semester_id=semester.id,
            teaching_class_id=teaching.id,
            college_id=service.college_id,
            weekday=item.weekday,
            start_period=item.start_period,
            end_period=item.end_period,
            classroom=item.classroom or None,
        )
        service._schedule_time(schedule, semester, weeks)
        service.db.add(schedule)
        service.db.flush()
        service.db.add_all(
            CourseScheduleWeek(schedule_id=schedule.id, week_no=week) for week in weeks
        )
        service.db.add_all(
            TeachingClassStudent(teaching_class_id=teaching.id, student_id=sid) for sid in students
        )
        teaching_count += 1
        schedule_count += 1
        student_count += len(students)
    service.db.flush()
    return service._audit(
        "academic.course.batch_elective_create",
        course,
        None,
        body.reason,
        after_extra={
            "course_id": str(course.id),
            "teaching_classes_created": teaching_count,
            "schedules_created": schedule_count,
            "students_enrolled": student_count,
        },
    )
