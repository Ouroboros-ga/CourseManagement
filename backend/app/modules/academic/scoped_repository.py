"""显式院级查询。详情和分页计数共享 SQL 谓词，不从身份缓存直接返回外院行。"""

from datetime import date

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, raiseload

from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
    VolunteerQualification,
)
from app.modules.academic.repository import _paged
from app.modules.identity.resource_scope import ResourceScope
from app.modules.identity.role_scope import business_today

AcademicModel = (
    type[AdministrativeClass]
    | type[Student]
    | type[TeachingClass]
    | type[CourseSchedule]
    | type[Course]
    | type[Semester]
    | type[VolunteerQualification]
)
RESOURCES: dict[str, AcademicModel] = {
    "administrative_classes": AdministrativeClass,
    "students": Student,
    "teaching_classes": TeachingClass,
    "schedules": CourseSchedule,
    "courses": Course,
    "semesters": Semester,
    "qualifications": VolunteerQualification,
}


class ScopedAcademicRepository:
    def __init__(self, db: Session, scope: ResourceScope):
        if not isinstance(scope, ResourceScope):
            raise ValueError("必须显式提供已解析的资源范围")
        self.db = db
        self.scope = scope

    def query(self, kind: str, *, as_of: date | None = None):
        model = RESOURCES.get(kind)
        if model is None:
            raise PermissionDeniedError("未实现的资源范围")
        permitted = {
            "administrative_classes": {
                "academic.read",
                "academic.manage",
                "student.read",
                "student.manage",
                "identity.binding.manage",
            },
            "teaching_classes": {
                "academic.read",
                "academic.manage",
                "student.read",
                "student.manage",
            },
            "students": {"student.read", "student.manage", "volunteer.manage", "identity.binding.manage"},
            "schedules": {"academic.read", "academic.manage"},
            "qualifications": {"volunteer.read"},
            "courses": {
                "academic.read",
                "academic.manage",
                "student.read",
                "student.manage",
                "volunteer.read",
            },
            "semesters": {
                "academic.read",
                "academic.manage",
                "student.read",
                "student.manage",
                "volunteer.read",
            },
        }
        if self.scope.action not in permitted[kind]:
            raise PermissionDeniedError("动作不匹配资源范围")
        cid = self.scope.college_id
        stmt = select(model).options(raiseload("*"))
        if model is AdministrativeClass:
            stmt = stmt.where(AdministrativeClass.college_id == cid)
        elif model is TeachingClass:
            stmt = stmt.where(TeachingClass.college_id == cid)
        elif model is CourseSchedule:
            teaching_ids = (
                select(TeachingClass.id).where(TeachingClass.college_id == cid).correlate(None)
            )
            stmt = stmt.where(
                and_(
                    CourseSchedule.college_id == cid,
                    CourseSchedule.teaching_class_id.in_(teaching_ids),
                )
            )
        elif model in (Student, VolunteerQualification):
            class_ids = (
                select(AdministrativeClass.id)
                .where(AdministrativeClass.college_id == cid)
                .correlate(None)
            )
            day = as_of or business_today()
            dated_ids = (
                select(StudentEnrollment.student_id)
                .where(
                    StudentEnrollment.college_id == cid,
                    StudentEnrollment.superseded.is_(False),
                    StudentEnrollment.effective_from <= day,
                    or_(
                        StudentEnrollment.effective_to.is_(None),
                        StudentEnrollment.effective_to > day,
                    ),
                )
                .correlate(None)
            )
            student_scope = or_(
                Student.id.in_(dated_ids),
                ~exists(select(1).where(StudentEnrollment.student_id == Student.id))
                & Student.administrative_class_id.in_(class_ids),
            )
            # 显式日期只返回有学籍事实的人员，不以今日投影伪造过去或未来归属。
            if as_of is not None:
                student_scope = Student.id.in_(dated_ids)
            if model is Student:
                stmt = stmt.where(student_scope)
            else:
                student_ids = select(Student.id).where(student_scope).correlate(None)
                stmt = stmt.where(
                    VolunteerQualification.student_id.in_(student_ids),
                    VolunteerQualification.college_id == cid,
                )
        elif model is Course:
            stmt = stmt.where(or_(Course.college_id.is_(None), Course.college_id == cid))
        elif model is not Semester:
            raise PermissionDeniedError()
        # Course/Semester 是显式学校共享只读目录；没有通用“不匹配则全表”的分支。
        return stmt.execution_options(populate_existing=True)

    def get(self, kind: str, resource_id: int, *, lock: bool = False):
        stmt = self.query(kind).where(RESOURCES[kind].id == resource_id)
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.scalar(stmt)
        if row is None:
            raise NotFoundError()
        return row

    def page(
        self,
        kind: str,
        params: PageParams,
        *,
        keyword: str | None = None,
        semester_id: int | None = None,
        administrative_class_id: int | None = None,
        as_of: date | None = None,
    ):
        stmt = self.query(kind, as_of=as_of)
        model = RESOURCES[kind]
        if keyword:
            column = {
                "administrative_classes": AdministrativeClass.class_name,
                "students": Student.name,
                "teaching_classes": TeachingClass.class_name,
                "courses": Course.course_name,
                "semesters": Semester.name,
            }.get(kind)
            if column is not None:
                condition = column.contains(keyword, autoescape=True)
                if model is Student:
                    condition = or_(condition, Student.student_no.contains(keyword, autoescape=True))
                stmt = stmt.where(condition)
        semester_column = {
            "teaching_classes": TeachingClass.semester_id,
            "schedules": CourseSchedule.semester_id,
            "qualifications": VolunteerQualification.semester_id,
        }.get(kind)
        if semester_id is not None and semester_column is not None:
            stmt = stmt.where(semester_column == semester_id)
        if administrative_class_id is not None and model is Student:
            day = as_of or business_today()
            stmt = stmt.where(
                or_(
                    Student.id.in_(
                        select(StudentEnrollment.student_id).where(
                            StudentEnrollment.administrative_class_id == administrative_class_id,
                            StudentEnrollment.superseded.is_(False),
                            StudentEnrollment.effective_from <= day,
                            or_(
                                StudentEnrollment.effective_to.is_(None),
                                StudentEnrollment.effective_to > day,
                            ),
                        )
                    ),
                    Student.id.not_in(select(StudentEnrollment.student_id))
                    & (Student.administrative_class_id == administrative_class_id),
                )
            )
        return _paged(self.db, stmt.order_by(model.id), params)

    def roster(self, teaching_class_id: int):
        self.get("teaching_classes", teaching_class_id)
        ids = (
            select(TeachingClassStudent.student_id)
            .where(TeachingClassStudent.teaching_class_id == teaching_class_id)
            .correlate(None)
        )
        # 首期不开放跨院名单。拒绝部分可见名单，避免把缺失人员当作真实名单。
        visible = list(self.db.scalars(self.query("students").where(Student.id.in_(ids))))
        all_ids = set(self.db.scalars(ids))
        if {row.id for row in visible} != all_ids:
            raise PermissionDeniedError("名单含外院或未确定归属学生，需先核对")
        return sorted(visible, key=lambda row: row.id)

    def students(self, ids: list[int]):
        return list(
            self.db.scalars(self.query("students").where(Student.id.in_(ids)).with_for_update())
        )

    def replace_roster(self, teaching_class_id: int, student_ids: list[int]):
        # 调用前 Service 锁定学院、教学班，并验证完整学生集合。
        if self.scope.action != "student.manage":
            raise PermissionDeniedError()
        rows = list(
            self.db.scalars(
                select(TeachingClassStudent).where(
                    TeachingClassStudent.teaching_class_id == teaching_class_id
                )
            )
        )
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        self.db.add_all(
            [
                TeachingClassStudent(teaching_class_id=teaching_class_id, student_id=sid)
                for sid in sorted(set(student_ids))
            ]
        )
