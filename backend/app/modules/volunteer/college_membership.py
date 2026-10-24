"""学院组只使用执行日期属于本院的学生；学籍未知时不回退当前班级。"""

from sqlalchemy import select

from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.models import AdministrativeClass, Student


def local_student_ids(college_id, day):
    dated = select(StudentEnrollment.student_id).where(
        StudentEnrollment.superseded.is_(False),
        StudentEnrollment.status == "ENROLLED",
        StudentEnrollment.college_id == college_id,
        StudentEnrollment.effective_from <= day,
        StudentEnrollment.effective_to.is_(None) | (StudentEnrollment.effective_to > day),
    )
    legacy = (
        Student.id.not_in(select(StudentEnrollment.student_id))
        & (Student.status == "ACTIVE")
        & Student.administrative_class_id.in_(
            select(AdministrativeClass.id).where(AdministrativeClass.college_id == college_id)
        )
    )
    return select(Student.id).where(Student.id.in_(dated) | legacy)
