"""按执行日期核对正式学籍和资格学院，不能靠当前班级或延迟投影推断。"""

from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.models import AdministrativeClass, Student, VolunteerQualification


def enrollment_on(db: Session, student_id: int, on_date: date, *, lock=False):
    table = StudentEnrollment.__table__
    query = select(table.c.status, table.c.administrative_class_id, table.c.college_id)
    query = (
        query
        .where(
            table.c.student_id == student_id,
            table.c.superseded.is_(False),
            table.c.effective_from <= on_date,
            or_(table.c.effective_to.is_(None), table.c.effective_to > on_date),
        )
        .order_by(table.c.effective_from.desc())
        .limit(1)
    )
    if lock:
        query = query.with_for_update(read=True)
    return db.execute(query).first()


def qualified_on(
    db: Session,
    qualification: VolunteerQualification | None,
    on_date: date,
    task_college_id: int | None = None,
    *,
    legacy_assignment_created_at: datetime | None = None,
) -> bool:
    if qualification is None or not qualification.enabled:
        return False
    enrolled = enrollment_on(db, qualification.student_id, on_date)
    if enrolled:
        if (
            enrolled.status != "ENROLLED"
            or enrolled.college_id is None
            or qualification.college_id != enrolled.college_id
        ):
            return False
        return task_college_id is None or task_college_id == enrolled.college_id
    table = StudentEnrollment.__table__
    baseline = db.execute(
        select(
            table.c.historical_confirmed,
            table.c.effective_from,
            table.c.created_at,
            table.c.college_id,
        )
        .where(table.c.student_id == qualification.student_id, table.c.revision == 0)
        .limit(1)
    ).first()
    if db.scalar(select(table.c.id).where(table.c.student_id == qualification.student_id).limit(1)):
        # 仅继承迁移前已有本人受派义务，不据此生成过去学籍或授予新排班资格。
        return bool(
            legacy_assignment_created_at is not None
            and baseline is not None
            and not baseline.historical_confirmed
            and on_date < baseline.effective_from
            and legacy_assignment_created_at <= baseline.created_at
            and (task_college_id is None or task_college_id == baseline.college_id)
            and qualification.college_id in {None, baseline.college_id}
        )
    student = db.get(Student, qualification.student_id)
    ac = (
        db.get(AdministrativeClass, student.administrative_class_id)
        if student and student.administrative_class_id
        else None
    )
    if student is None or student.status != "ACTIVE":
        return False
    return task_college_id is None or (ac is not None and ac.college_id == task_college_id)
