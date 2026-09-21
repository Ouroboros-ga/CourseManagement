"""基础数据模块仓储层：仅执行查询与最小持久化，复用 Service 传入的 Session，绝不自行 commit。

约定（与 identity/repository.py 一致，技术方案 5.1、PERMISSIONS.md 13.2）：
- 只负责取数、加锁读、增删改 ORM 对象并 flush 取得主键，提交由 Service 统一负责；
- 需要行级串行的写路径使用 `*_for_update`（SELECT ... FOR UPDATE + populate_existing）；
- 列表查询返回 (items, total)，分页由 Service 传入 PageParams 决定。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
    VolunteerQualification,
)


def _paged(session: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    """对已构造的实体查询施加排序/分页，并计算满足条件的总数。

    count 以去掉 order/limit/offset 的过滤子查询为源，items 再套用分页；
    join 可能带来的重复实体由 .unique() 依主键去重。
    """
    count_sub = stmt.order_by(None).subquery()
    total = session.execute(select(func.count()).select_from(count_sub)).scalar_one()
    items = list(
        session.execute(stmt.limit(params.limit).offset(params.offset)).scalars().unique().all()
    )
    return items, int(total)


class AcademicRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ==================== 通用 ====================
    def add(self, obj: object) -> None:
        self._session.add(obj)

    def flush(self) -> None:
        self._session.flush()

    # ==================== 学期 ====================
    def get_semester(self, semester_id: int) -> Semester | None:
        return self._session.get(Semester, semester_id)

    def get_semester_for_update(self, semester_id: int) -> Semester | None:
        stmt = (
            select(Semester)
            .where(Semester.id == semester_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_semester_by_code(self, code: str) -> Semester | None:
        return self._session.execute(
            select(Semester).where(Semester.code == code)
        ).scalar_one_or_none()

    def list_semesters(
        self, params: PageParams, *, status: str | None
    ) -> tuple[list[Semester], int]:
        stmt = select(Semester)
        if status:
            stmt = stmt.where(Semester.status == status)
        stmt = stmt.order_by(Semester.id)
        return _paged(self._session, stmt, params)

    # ==================== 节次定义 ====================
    def list_period_definitions(self, semester_id: int) -> list[PeriodDefinition]:
        return list(
            self._session.execute(
                select(PeriodDefinition)
                .where(PeriodDefinition.semester_id == semester_id)
                .order_by(PeriodDefinition.period_no)
            )
            .scalars()
            .all()
        )

    def get_period_definition(self, pd_id: int) -> PeriodDefinition | None:
        return self._session.get(PeriodDefinition, pd_id)

    def get_period_definition_by_no(
        self, semester_id: int, period_no: int
    ) -> PeriodDefinition | None:
        return self._session.execute(
            select(PeriodDefinition).where(
                PeriodDefinition.semester_id == semester_id,
                PeriodDefinition.period_no == period_no,
            )
        ).scalar_one_or_none()

    # ==================== 校历覆盖 ====================
    def list_calendar_overrides(self, semester_id: int) -> list[CalendarOverride]:
        return list(
            self._session.execute(
                select(CalendarOverride)
                .where(CalendarOverride.semester_id == semester_id)
                .order_by(CalendarOverride.date)
            )
            .scalars()
            .all()
        )

    def get_calendar_override(self, co_id: int) -> CalendarOverride | None:
        return self._session.get(CalendarOverride, co_id)

    def get_calendar_override_by_date(self, semester_id: int, on_date) -> CalendarOverride | None:
        return self._session.execute(
            select(CalendarOverride).where(
                CalendarOverride.semester_id == semester_id,
                CalendarOverride.date == on_date,
            )
        ).scalar_one_or_none()

    def delete_calendar_override(self, co: CalendarOverride) -> None:
        self._session.delete(co)
        self._session.flush()

    # ==================== 行政班 ====================
    def get_admin_class(self, class_id: int) -> AdministrativeClass | None:
        return self._session.get(AdministrativeClass, class_id)

    def get_admin_class_for_update(self, class_id: int) -> AdministrativeClass | None:
        stmt = (
            select(AdministrativeClass)
            .where(AdministrativeClass.id == class_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_admin_class_by_code(self, class_code: str) -> AdministrativeClass | None:
        return self._session.execute(
            select(AdministrativeClass).where(AdministrativeClass.class_code == class_code)
        ).scalar_one_or_none()

    def list_admin_classes(
        self, params: PageParams, *, college: str | None, status: str | None, keyword: str | None
    ) -> tuple[list[AdministrativeClass], int]:
        stmt = select(AdministrativeClass)
        if college:
            stmt = stmt.where(AdministrativeClass.college == college)
        if status:
            stmt = stmt.where(AdministrativeClass.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    AdministrativeClass.class_code.like(like),
                    AdministrativeClass.class_name.like(like),
                )
            )
        stmt = stmt.order_by(AdministrativeClass.id)
        return _paged(self._session, stmt, params)

    # ==================== 学生 ====================
    def get_student(self, student_id: int) -> Student | None:
        return self._session.get(Student, student_id)

    def get_student_for_update(self, student_id: int) -> Student | None:
        stmt = (
            select(Student)
            .where(Student.id == student_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_student_by_no(self, student_no: str) -> Student | None:
        return self._session.execute(
            select(Student).where(Student.student_no == student_no)
        ).scalar_one_or_none()

    def get_students_by_ids(self, ids: Sequence[int]) -> list[Student]:
        if not ids:
            return []
        return list(
            self._session.execute(select(Student).where(Student.id.in_(ids))).scalars().all()
        )

    def list_students(
        self,
        params: PageParams,
        *,
        administrative_class_id: int | None,
        college: str | None,
        status: str | None,
        keyword: str | None,
    ) -> tuple[list[Student], int]:
        stmt = select(Student)
        if administrative_class_id is not None:
            stmt = stmt.where(Student.administrative_class_id == administrative_class_id)
        if college:
            stmt = stmt.join(
                AdministrativeClass, Student.administrative_class_id == AdministrativeClass.id
            ).where(AdministrativeClass.college == college)
        if status:
            stmt = stmt.where(Student.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(Student.student_no.like(like), Student.name.like(like)))
        stmt = stmt.order_by(Student.id)
        return _paged(self._session, stmt, params)

    # ==================== 课程 ====================
    def get_course(self, course_id: int) -> Course | None:
        return self._session.get(Course, course_id)

    def get_course_for_update(self, course_id: int) -> Course | None:
        stmt = (
            select(Course)
            .where(Course.id == course_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_course_by_code(self, course_code: str) -> Course | None:
        return self._session.execute(
            select(Course).where(Course.course_code == course_code)
        ).scalar_one_or_none()

    def list_courses(
        self, params: PageParams, *, status: str | None, keyword: str | None
    ) -> tuple[list[Course], int]:
        stmt = select(Course)
        if status:
            stmt = stmt.where(Course.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(Course.course_code.like(like), Course.course_name.like(like)))
        stmt = stmt.order_by(Course.id)
        return _paged(self._session, stmt, params)

    # ==================== 教学班 ====================
    def get_teaching_class(self, tc_id: int) -> TeachingClass | None:
        return self._session.get(TeachingClass, tc_id)

    def get_teaching_class_for_update(self, tc_id: int) -> TeachingClass | None:
        stmt = (
            select(TeachingClass)
            .where(TeachingClass.id == tc_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_teaching_class_by_key(
        self, semester_id: int, course_id: int, class_code: str | None
    ) -> TeachingClass | None:
        stmt = select(TeachingClass).where(
            TeachingClass.semester_id == semester_id,
            TeachingClass.course_id == course_id,
        )
        stmt = stmt.where(
            TeachingClass.class_code.is_(None)
            if class_code is None
            else TeachingClass.class_code == class_code
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_teaching_classes(
        self,
        params: PageParams,
        *,
        semester_id: int | None,
        course_id: int | None,
        status: str | None,
    ) -> tuple[list[TeachingClass], int]:
        stmt = select(TeachingClass)
        if semester_id is not None:
            stmt = stmt.where(TeachingClass.semester_id == semester_id)
        if course_id is not None:
            stmt = stmt.where(TeachingClass.course_id == course_id)
        if status:
            stmt = stmt.where(TeachingClass.status == status)
        stmt = stmt.order_by(TeachingClass.id)
        return _paged(self._session, stmt, params)

    def get_roster_students(self, tc_id: int) -> list[Student]:
        return list(
            self._session.execute(
                select(Student)
                .join(TeachingClassStudent, TeachingClassStudent.student_id == Student.id)
                .where(TeachingClassStudent.teaching_class_id == tc_id)
                .order_by(Student.id)
            )
            .scalars()
            .all()
        )

    def set_roster(self, tc_id: int, student_ids: Sequence[int]) -> None:
        """整体替换教学班名单：删除关联行，插入去重后的目标集合。"""
        existing = (
            self._session.execute(
                select(TeachingClassStudent).where(TeachingClassStudent.teaching_class_id == tc_id)
            )
            .scalars()
            .all()
        )
        for row in existing:
            self._session.delete(row)
        self._session.flush()
        for sid in dict.fromkeys(student_ids):  # 去重保序
            self._session.add(TeachingClassStudent(teaching_class_id=tc_id, student_id=sid))
        self._session.flush()

    # ==================== 课表 ====================
    def get_schedule(self, schedule_id: int) -> CourseSchedule | None:
        return self._session.get(CourseSchedule, schedule_id)

    def get_schedule_for_update(self, schedule_id: int) -> CourseSchedule | None:
        stmt = (
            select(CourseSchedule)
            .where(CourseSchedule.id == schedule_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_schedules(
        self,
        params: PageParams,
        *,
        semester_id: int | None,
        teaching_class_id: int | None,
        status: str | None,
    ) -> tuple[list[CourseSchedule], int]:
        stmt = select(CourseSchedule)
        if semester_id is not None:
            stmt = stmt.where(CourseSchedule.semester_id == semester_id)
        if teaching_class_id is not None:
            stmt = stmt.where(CourseSchedule.teaching_class_id == teaching_class_id)
        if status:
            stmt = stmt.where(CourseSchedule.status == status)
        stmt = stmt.order_by(CourseSchedule.id)
        return _paged(self._session, stmt, params)

    def set_schedule_weeks(self, schedule: CourseSchedule, week_nos: Sequence[int]) -> None:
        """整体替换课表生效周次（级联删除旧行）。"""
        schedule.weeks = [CourseScheduleWeek(week_no=w) for w in sorted(dict.fromkeys(week_nos))]
        self._session.flush()

    def delete_schedule(self, schedule: CourseSchedule) -> None:
        self._session.delete(schedule)
        self._session.flush()

    # ==================== 志愿者资格 ====================
    def get_volunteer_qualification(self, vq_id: int) -> VolunteerQualification | None:
        return self._session.get(VolunteerQualification, vq_id)

    def get_volunteer_qualification_by_sem_student(
        self, semester_id: int, student_id: int
    ) -> VolunteerQualification | None:
        return self._session.execute(
            select(VolunteerQualification).where(
                VolunteerQualification.semester_id == semester_id,
                VolunteerQualification.student_id == student_id,
            )
        ).scalar_one_or_none()

    def list_volunteer_qualifications(
        self,
        params: PageParams,
        *,
        semester_id: int | None,
        enabled: bool | None,
    ) -> tuple[list[VolunteerQualification], int]:
        stmt = select(VolunteerQualification)
        if semester_id is not None:
            stmt = stmt.where(VolunteerQualification.semester_id == semester_id)
        if enabled is not None:
            stmt = stmt.where(VolunteerQualification.enabled.is_(enabled))
        stmt = stmt.order_by(VolunteerQualification.id)
        return _paged(self._session, stmt, params)

    # ---- 供 Service 判定"学生是否仍持有其它有效学期资格"（撤销 VOLUNTEER 身份用）----
    def count_enabled_volunteer_qualifications(self, student_id: int) -> int:
        return int(
            self._session.execute(
                select(func.count())
                .select_from(VolunteerQualification)
                .where(
                    VolunteerQualification.student_id == student_id,
                    VolunteerQualification.enabled.is_(True),
                )
            ).scalar_one()
        )
