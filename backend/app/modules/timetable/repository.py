"""每次核对当前账号绑定，写操作用账号、学生和个人聚合行的固定锁序。"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import AdministrativeClass, Semester, Student
from app.modules.academic.publication_models import AcademicPublication, PublicationAudience
from app.modules.identity.models import UserAccount
from app.modules.timetable.models import PersonalTimetable


class PersonalTimetableRepository:
    def __init__(self, db: Session):
        self.db = db

    def student(self, user_id: int, *, lock=False):
        user_stmt = select(UserAccount).where(UserAccount.id == user_id)
        if lock:
            user_stmt = user_stmt.with_for_update()
        user = self.db.scalar(user_stmt.execution_options(populate_existing=True))
        if user is None or user.status != "ACTIVE" or user.student_id is None:
            raise PermissionDeniedError("请先完成有效学生绑定")
        stmt = select(Student).where(Student.id == user.student_id)
        if lock:
            stmt = stmt.with_for_update()
        student = self.db.scalar(stmt.execution_options(populate_existing=True))
        if student is None or student.status != "ACTIVE":
            raise PermissionDeniedError("学生身份已停用")
        return student

    def get(self, student_id: int, semester_id: int, *, lock=False):
        if self.db.scalar(select(Semester.id).where(Semester.id == semester_id)) is None:
            raise NotFoundError("学期不存在")
        stmt = select(PersonalTimetable).where(
            PersonalTimetable.student_id == student_id, PersonalTimetable.semester_id == semester_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return self.db.scalar(stmt.execution_options(populate_existing=True))

    def semesters(self, student_id: int):
        own_college = (
            select(AdministrativeClass.college_id)
            .join(Student, Student.administrative_class_id == AdministrativeClass.id)
            .where(Student.id == student_id)
        )
        audience = select(PublicationAudience.publication_id).where(
            PublicationAudience.student_id == student_id
        )
        published = select(AcademicPublication.semester_id).where(
            or_(
                AcademicPublication.college_id.in_(own_college),
                AcademicPublication.id.in_(audience),
            )
        )
        initialized = select(PersonalTimetable.semester_id).where(
            PersonalTimetable.student_id == student_id
        )
        return list(
            self.db.execute(
                select(Semester, PersonalTimetable.current_version)
                .outerjoin(
                    PersonalTimetable,
                    (PersonalTimetable.semester_id == Semester.id)
                    & (PersonalTimetable.student_id == student_id),
                )
                .where(or_(Semester.id.in_(published), Semester.id.in_(initialized)))
                .order_by(Semester.start_date.desc(), Semester.id.desc())
            )
        )
