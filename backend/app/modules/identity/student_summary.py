"""只读的本人学生资料摘要；身份由绑定ID确定，不从姓名、角色或学号文本猜测。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.models import UserAccount
from app.modules.identity.role_scope import business_today
from app.modules.organization.models import College


def student_summary(db: Session, account: UserAccount | None) -> dict | None:
    if account is None or account.status != "ACTIVE" or account.student_id is None:
        return None
    student = db.scalar(select(Student).where(Student.id == account.student_id))
    if student is None:
        return None
    enrollments = EnrollmentService(db)
    current = enrollments.at(student.id, business_today())
    if current is not None:
        class_id, college_id = current.administrative_class_id, current.college_id
        state = current.status
    elif not enrollments.has_timeline(student.id):
        # 无时间线的旧数据允许展示当前档案；已有时间线但当前空缺时不能猜补。
        class_id, college_id, state = student.administrative_class_id, None, student.status
    else:
        class_id, college_id, state = None, None, None
    classroom = db.get(AdministrativeClass, class_id) if class_id is not None else None
    if current is None and classroom is not None:
        college_id = classroom.college_id
    college = db.get(College, college_id) if college_id is not None else None
    return {
        "student_id": str(student.id), "student_no": student.student_no, "name": student.name,
        "administrative_class_id": str(class_id) if class_id is not None else None,
        "administrative_class_name": classroom.class_name if classroom is not None else None,
        "college_id": str(college_id) if college_id is not None else None,
        "college_name": college.name if college is not None else None,
        "enrollment_status": state,
    }
