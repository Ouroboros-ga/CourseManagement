"""正式名单按课次日期解析；个人显示课表不在输入中。"""

from collections import defaultdict
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.models import Student, TeachingClassStudent


def rosters_at(
    session: Session, teaching_class_ids: list[int], on_date: date
) -> dict[int, list[Student]]:
    from app.modules.identity.query_scope import query_date

    with query_date(session, on_date):
        return _rosters_at(session, teaching_class_ids, on_date)


def _rosters_at(
    session: Session, teaching_class_ids: list[int], on_date: date
) -> dict[int, list[Student]]:
    """每个日期批量读，避免按每人每课次执行数据库查询。"""
    tids = set(teaching_class_ids)
    if not tids:
        return {}
    if session.info.get("college_query_scope"):
        from app.core.exceptions import ConflictError
        from app.modules.academic.models import TeachingClass

        visible = set(session.scalars(select(TeachingClass.id).where(TeachingClass.id.in_(tids))))
        if visible != tids:
            raise ConflictError(message="名单来源含外院教学班，请管理员统筹处理")
    audiences: dict[int, set[int]] = defaultdict(set)
    for tid, cid in session.execute(
        select(
            TeachingClassAudience.teaching_class_id, TeachingClassAudience.administrative_class_id
        ).where(TeachingClassAudience.teaching_class_id.in_(tids))
    ):
        audiences[tid].add(cid)
    dated = list(
        session.scalars(
            select(CourseParticipation).where(CourseParticipation.teaching_class_id.in_(tids))
        )
    )
    dated_ids: dict[int, set[int]] = defaultdict(set)
    explicit: dict[int, set[int]] = defaultdict(set)
    for member in dated:
        dated_ids[member.teaching_class_id].add(member.student_id)
        if member.effective_from <= on_date and (
            member.effective_to is None or on_date < member.effective_to
        ):
            explicit[member.teaching_class_id].add(member.student_id)
    legacy: dict[int, set[int]] = defaultdict(set)
    for tid, sid in session.execute(
        select(TeachingClassStudent.teaching_class_id, TeachingClassStudent.student_id).where(
            TeachingClassStudent.teaching_class_id.in_(tids)
        )
    ):
        if sid not in dated_ids[tid] and not audiences[tid]:
            legacy[tid].add(sid)
    candidate_ids = set().union(*explicit.values(), *legacy.values())
    class_ids = set().union(*audiences.values())
    any_timeline = select(StudentEnrollment.student_id)
    if class_ids:
        current = select(StudentEnrollment.student_id).where(
            StudentEnrollment.administrative_class_id.in_(class_ids),
            StudentEnrollment.superseded.is_(False),
            StudentEnrollment.effective_from <= on_date,
            or_(StudentEnrollment.effective_to.is_(None), StudentEnrollment.effective_to > on_date),
        )
        candidate_ids.update(
            session.scalars(
                select(Student.id).where(
                    or_(
                        Student.id.in_(current),
                        Student.id.not_in(any_timeline)
                        & Student.administrative_class_id.in_(class_ids),
                    )
                )
            )
        )
    if not candidate_ids:
        return {tid: [] for tid in tids}
    students = list(
        session.scalars(select(Student).where(Student.id.in_(candidate_ids)).order_by(Student.id))
    )
    if session.info.get("college_query_scope"):
        missing = candidate_ids - {s.id for s in students}
        if missing:
            from app.core.exceptions import ConflictError

            table = StudentEnrollment.__table__
            enrolled_missing = select(table.c.student_id).where(
                table.c.student_id.in_(missing),
                table.c.superseded.is_(False),
                table.c.status == "ENROLLED",
                table.c.effective_from <= on_date,
                or_(table.c.effective_to.is_(None), table.c.effective_to > on_date),
            )
            legacy_missing = select(Student.__table__.c.id).where(
                Student.__table__.c.id.in_(missing),
                Student.__table__.c.id.not_in(select(table.c.student_id)),
                Student.__table__.c.status == "ACTIVE",
            )
            if (
                session.scalar(enrolled_missing.limit(1)) is not None
                or session.scalar(legacy_missing.limit(1)) is not None
            ):
                raise ConflictError(
                    message="课程存在跨院在读名单，请管理员统筹处理，系统不会自动删去不可见成员"
                )
    enrollments = list(
        session.scalars(
            select(StudentEnrollment).where(StudentEnrollment.student_id.in_(candidate_ids))
        )
    )
    timeline_ids = {e.student_id for e in enrollments}
    active = {
        e.student_id: e
        for e in enrollments
        if not e.superseded
        and e.effective_from <= on_date
        and (e.effective_to is None or on_date < e.effective_to)
    }
    result: dict[int, list[Student]] = {tid: [] for tid in tids}
    for student in students:
        enrollment = active.get(student.id)
        if enrollment is not None:
            enrolled = enrollment.status == "ENROLLED"
            class_id = enrollment.administrative_class_id
        else:
            # 有时间轴而该日期未知时，不能用当前班级编造历史。
            enrolled = student.id not in timeline_ids and student.status == "ACTIVE"
            class_id = student.administrative_class_id if enrolled else None
        if enrolled:
            for tid in tids:
                if student.id in explicit[tid] | legacy[tid] or class_id in audiences[tid]:
                    result[tid].append(student)
    return result


def roster_at(session: Session, teaching_class_id: int, on_date: date) -> list[Student]:
    return rosters_at(session, [teaching_class_id], on_date).get(teaching_class_id, [])
