"""显式院级查询。详情和分页计数共享 SQL 谓词，不从身份缓存直接返回外院行。"""

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, raiseload

from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError, PermissionDeniedError
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

    def query(self, kind: str):
        model = RESOURCES.get(kind)
        if model is None:
            raise PermissionDeniedError("未实现的资源范围")
        permitted = {
            "administrative_classes": {"academic.read", "academic.manage"},
            "teaching_classes": {
                "academic.read",
                "academic.manage",
                "student.read",
                "student.manage",
            },
            "students": {"student.read", "student.manage"},
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
        class_ids = (
            select(AdministrativeClass.id)
            .where(AdministrativeClass.college_id == cid)
            .correlate(None)
        )
        teaching_ids = (
            select(TeachingClass.id).where(TeachingClass.college_id == cid).correlate(None)
        )
        student_ids = (
            select(Student.id).where(Student.administrative_class_id.in_(class_ids)).correlate(None)
        )
        stmt = select(model).options(raiseload("*"))
        if model is AdministrativeClass:
            stmt = stmt.where(AdministrativeClass.college_id == cid)
        elif model is TeachingClass:
            stmt = stmt.where(TeachingClass.college_id == cid)
        elif model is CourseSchedule:
            stmt = stmt.where(
                and_(
                    CourseSchedule.college_id == cid,
                    CourseSchedule.teaching_class_id.in_(teaching_ids),
                )
            )
        elif model is Student:
            stmt = stmt.where(Student.administrative_class_id.in_(class_ids))
        elif model is VolunteerQualification:
            stmt = stmt.where(VolunteerQualification.student_id.in_(student_ids))
        elif model not in (Course, Semester):
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
    ):
        stmt = self.query(kind)
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
                stmt = stmt.where(column.contains(keyword, autoescape=True))
        semester_column = {
            "teaching_classes": TeachingClass.semester_id,
            "schedules": CourseSchedule.semester_id,
            "qualifications": VolunteerQualification.semester_id,
        }.get(kind)
        if semester_id is not None and semester_column is not None:
            stmt = stmt.where(semester_column == semester_id)
        if administrative_class_id is not None and model is Student:
            stmt = stmt.where(Student.administrative_class_id == administrative_class_id)
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
