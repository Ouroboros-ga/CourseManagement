"""选修名单替换保留日期区间；班级课源由正式学籍驱动。"""

from datetime import date

from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.modules.academic.enrollment_models import CourseParticipation, TeachingClassAudience
from app.modules.academic.models import TeachingClassStudent


def record_roster_replacement(
    db, teaching_class_id: int, student_ids: list[int], on_date: date
) -> None:
    if (
        db.scalar(
            select(TeachingClassAudience.teaching_class_id)
            .where(TeachingClassAudience.teaching_class_id == teaching_class_id)
            .limit(1)
        )
        is not None
    ):
        raise ConflictError(message="此课程名单由行政班学籍驱动，请通过学生交接与学籍流程维护")
    existing = set(
        db.scalars(
            select(TeachingClassStudent.student_id).where(
                TeachingClassStudent.teaching_class_id == teaching_class_id
            )
        )
    )
    wanted = set(student_ids)
    from app.modules.academic.enrollment_service import EnrollmentService
    from app.modules.academic.models import Student

    lifecycle = EnrollmentService(db)
    for sid in wanted:
        enrollment = lifecycle.at(sid, on_date)
        student = db.get(Student, sid)
        if (
            student is None
            or (enrollment is not None and enrollment.status != "ENROLLED")
            or (enrollment is None and (lifecycle.has_timeline(sid) or student.status != "ACTIVE"))
        ):
            raise ConflictError(message="正式课程成员必须有有效在读学籍")
    records = list(
        db.scalars(
            select(CourseParticipation)
            .where(CourseParticipation.teaching_class_id == teaching_class_id)
            .with_for_update()
        )
    )
    by_student: dict[int, list[CourseParticipation]] = {}
    for r in records:
        by_student.setdefault(r.student_id, []).append(r)
        if r.effective_from > on_date:
            raise ConflictError(message="已有后续选课计划，不能用当前名单覆盖，请先核对计划")
    for sid in existing | wanted:
        active = [
            r
            for r in by_student.get(sid, [])
            if r.effective_from <= on_date and (r.effective_to is None or r.effective_to > on_date)
        ]
        if sid in existing and sid not in wanted and not by_student.get(sid):
            db.add(
                CourseParticipation(
                    teaching_class_id=teaching_class_id,
                    student_id=sid,
                    effective_from=date(1000, 1, 1),
                    effective_to=on_date,
                    source="LEGACY_UNCONFIRMED",
                )
            )
        elif sid not in wanted:
            for r in active:
                if r.effective_from == on_date:
                    db.delete(r)
                else:
                    r.effective_to = on_date
        elif not active and (sid not in existing or by_student.get(sid)):
            db.add(
                CourseParticipation(
                    teaching_class_id=teaching_class_id,
                    student_id=sid,
                    effective_from=on_date,
                    source="EXPLICIT",
                )
            )
