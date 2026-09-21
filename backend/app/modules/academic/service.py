"""基础数据模块服务层：业务规则、事务边界与审计（技术方案 9.1/9.2，PERMISSIONS.md 13.2）。

统一约定（与 identity/service.py 一致）：
- 同步 Session，由 Router 依赖注入；每个写方法成功路径末尾**单次 commit**，失败抛 AppError
  由依赖回滚关闭。Repository 只 flush 不 commit。
- 写路径在同一事务内对目标行 `SELECT ... FOR UPDATE`（populate_existing）串行化并发写；
  涉及父资源（学期）的先锁父再操作子，固定加锁顺序（按外键层级、子实体按 ID 升序）防死锁。
- 事务内纵深重验：重读操作者有效权限 → 校验父学期状态 → 校验引用存在 → 校验业务约束
  → 变更 → 追加审计（同事务）→ 提交。
- 审计 append-only，resource_type 用稳定名，before/after 记录关键差异。

乐观并发说明：基础数据表不设 lock_version（低频后台维护），并发一致性由行级 FOR UPDATE
与唯一约束保证；这与 user_account 的 lock_version 机制有意不同，见 PERMISSIONS.md 13.2 备注。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import select

from app.common.pagination import PageParams
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.core.permissions import PermissionCode, RoleCode
from app.modules.academic import permissions as perms
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    OverrideType,
    PeriodDefinition,
    Semester,
    SemesterStatus,
    Student,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.academic.repository import AcademicRepository
from app.modules.academic.schemas import (
    AdministrativeClassCreateRequest,
    AdministrativeClassResponse,
    AdministrativeClassUpdateRequest,
    CalendarOverrideCreateRequest,
    CalendarOverrideResponse,
    CourseCreateRequest,
    CourseResponse,
    CourseScheduleCreateRequest,
    CourseScheduleResponse,
    CourseScheduleUpdateRequest,
    CourseUpdateRequest,
    PeriodDefinitionResponse,
    PeriodDefinitionUpsertRequest,
    SemesterCreateRequest,
    SemesterResponse,
    SemesterUpdateRequest,
    StudentCreateRequest,
    StudentResponse,
    StudentUpdateRequest,
    TeachingClassCreateRequest,
    TeachingClassResponse,
    TeachingClassUpdateRequest,
    VolunteerQualificationResponse,
    VolunteerQualificationUpsertRequest,
)
from app.modules.audit.models import AuditLog
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser


def _page(items: list, total: int, params: PageParams) -> dict:
    return {
        "items": [i.model_dump() for i in items],
        "page": params.page,
        "page_size": params.page_size,
        "total": total,
    }


def _sched_dto(s: CourseSchedule) -> CourseScheduleResponse:
    return CourseScheduleResponse(
        id=s.id,
        semester_id=s.semester_id,
        teaching_class_id=s.teaching_class_id,
        weekday=s.weekday,
        start_period=s.start_period,
        end_period=s.end_period,
        classroom=s.classroom,
        status=s.status,
        weeks=[w.week_no for w in s.weeks],
    )


class AcademicService:
    def __init__(self, session) -> None:  # noqa: ANN001 - Session 由依赖注入
        self._session = session
        self._repo = AcademicRepository(session)
        self._identity = IdentityRepository(session)

    # ================================================================== #
    # 公共守卫与审计
    # ================================================================== #
    def _require_actor_permission(self, actor_user_id: int, code: str) -> None:
        """事务内重读操作者有效权限并校验（纵深防御，PERMISSIONS.md 13.2）。"""
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None:
            raise UnauthenticatedError("操作者账号不可用")
        effective = set(self._identity.list_effective_permissions(actor_user_id))
        if code not in effective:
            raise PermissionDeniedError()

    def _record_audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_type: str,
        resource_id: str,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_json=dict(before) if before is not None else None,
                after_json=dict(after) if after is not None else None,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()

    def _require_active_semester(self, semester_id: int) -> Semester:
        """锁定并返回处于 ACTIVE 的学期；不存在 404，归档 409。"""
        sem = self._repo.get_semester_for_update(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != SemesterStatus.ACTIVE.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期已归档，禁止写入")
        return sem

    @staticmethod
    def _validate_status(status: str | None) -> None:
        if status is not None and status not in perms.ALLOWED_RECORD_STATUS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "非法状态值",
                http_status=422,
                field_errors={"status": status},
            )

    # ================================================================== #
    # 学期
    # ================================================================== #
    def create_semester(self, actor: CurrentUser, body: SemesterCreateRequest, request_id):  # noqa: ANN001
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        if self._repo.get_semester_by_code(body.code) is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期代码已存在")
        if body.end_date < body.start_date:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束日期不得早于开始日期", http_status=422)
        sem = Semester(
            code=body.code,
            name=body.name,
            start_date=body.start_date,
            end_date=body.end_date,
            first_monday=body.first_monday,
            total_weeks=body.total_weeks,
            status=SemesterStatus.ACTIVE.value,
        )
        self._repo.add(sem)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.semester.create",
            resource_type="semester",
            resource_id=str(sem.id),
            before=None,
            after={"code": sem.code, "name": sem.name},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return SemesterResponse.model_validate(sem)

    def update_semester(
        self,
        actor: CurrentUser,
        semester_id: int,
        body: SemesterUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> SemesterResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        sem = self._repo.get_semester_for_update(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if body.status is not None and body.status not in perms.ALLOWED_SEMESTER_STATUS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "非法学期状态",
                http_status=422,
                field_errors={"status": body.status},
            )
        before = {"name": sem.name, "status": sem.status, "total_weeks": sem.total_weeks}
        if body.name is not None:
            sem.name = body.name
        if body.start_date is not None:
            sem.start_date = body.start_date
        if body.end_date is not None:
            sem.end_date = body.end_date
        if body.first_monday is not None:
            sem.first_monday = body.first_monday
        if body.total_weeks is not None:
            sem.total_weeks = body.total_weeks
        if body.status is not None:
            sem.status = body.status
        if sem.end_date < sem.start_date:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束日期不得早于开始日期", http_status=422)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.semester.update",
            resource_type="semester",
            resource_id=str(sem.id),
            before=before,
            after={"name": sem.name, "status": sem.status, "total_weeks": sem.total_weeks},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return SemesterResponse.model_validate(sem)

    def get_semester(self, semester_id: int) -> SemesterResponse:
        sem = self._repo.get_semester(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        return SemesterResponse.model_validate(sem)

    def list_semesters(self, params: PageParams, *, status: str | None) -> dict:
        rows, total = self._repo.list_semesters(params, status=status)
        return _page([SemesterResponse.model_validate(s) for s in rows], total, params)

    # ================================================================== #
    # 节次定义（学期子资源）
    # ================================================================== #
    def upsert_period_definition(
        self,
        actor: CurrentUser,
        semester_id: int,
        body: PeriodDefinitionUpsertRequest,
        request_id,  # noqa: ANN001
    ) -> PeriodDefinitionResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        sem = self._require_active_semester(semester_id)
        if body.period_no is None or body.period_no < 1 or body.period_no > 20:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "节次号须在 1..20 范围内",
                http_status=422,
                field_errors={"period_no": body.period_no},
            )
        period_no = body.period_no
        if (
            body.start_time is not None
            and body.end_time is not None
            and body.end_time <= body.start_time
        ):
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "节次结束时刻须晚于开始时刻", http_status=422
            )
        existing = self._repo.get_period_definition_by_no(sem.id, period_no)
        created = existing is None
        pd = (
            existing
            if existing is not None
            else PeriodDefinition(semester_id=sem.id, period_no=period_no)
        )
        if created:
            self._repo.add(pd)
        pd.start_time = body.start_time
        pd.end_time = body.end_time
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.period_definition.upsert",
            resource_type="period_definition",
            resource_id=str(pd.id),
            before=None if created else {"start_time": str(pd.start_time or "")},
            after={"period_no": pd.period_no, "semester_id": sem.id},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return PeriodDefinitionResponse.model_validate(pd)

    def list_period_definitions(self, semester_id: int) -> list[PeriodDefinitionResponse]:
        if self._repo.get_semester(semester_id) is None:
            raise NotFoundError("学期不存在")
        rows = self._repo.list_period_definitions(semester_id)
        return [PeriodDefinitionResponse.model_validate(r) for r in rows]

    def delete_period_definition(
        self,
        actor: CurrentUser,
        semester_id: int,
        period_id: int,
        reason,
        request_id,  # noqa: ANN001
    ) -> None:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._require_active_semester(semester_id)
        pd = self._repo.get_period_definition(period_id)
        if pd is None or pd.semester_id != semester_id:
            raise NotFoundError("节次定义不存在")
        self._session.delete(pd)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.period_definition.delete",
            resource_type="period_definition",
            resource_id=str(period_id),
            before={"period_no": pd.period_no},
            after=None,
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()

    # ================================================================== #
    # 校历覆盖（学期子资源）
    # ================================================================== #
    def create_calendar_override(
        self,
        actor: CurrentUser,
        semester_id: int,
        body: CalendarOverrideCreateRequest,
        request_id,  # noqa: ANN001
    ) -> CalendarOverrideResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        sem = self._require_active_semester(semester_id)
        if body.override_type not in perms.ALLOWED_OVERRIDE_TYPE:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "非法校历覆盖类型",
                http_status=422,
                field_errors={"override_type": body.override_type},
            )
        if body.override_type == OverrideType.MAKEUP.value and body.source_teaching_weekday is None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "调休/补课必须指定来源教学星期",
                http_status=422,
                field_errors={"source_teaching_weekday": "required_for_makeup"},
            )
        if self._repo.get_calendar_override_by_date(sem.id, body.date) is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该日期已存在校历覆盖")
        co = CalendarOverride(
            semester_id=sem.id,
            date=body.date,
            override_type=body.override_type,
            source_teaching_weekday=body.source_teaching_weekday,
            reason=body.reason,
        )
        self._repo.add(co)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.calendar_override.create",
            resource_type="calendar_override",
            resource_id=str(co.id),
            before=None,
            after={"date": co.date.isoformat(), "override_type": co.override_type},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return CalendarOverrideResponse.model_validate(co)

    def list_calendar_overrides(self, semester_id: int) -> list[CalendarOverrideResponse]:
        if self._repo.get_semester(semester_id) is None:
            raise NotFoundError("学期不存在")
        rows = self._repo.list_calendar_overrides(semester_id)
        return [CalendarOverrideResponse.model_validate(r) for r in rows]

    def delete_calendar_override(
        self,
        actor: CurrentUser,
        semester_id: int,
        override_id: int,
        reason,
        request_id,  # noqa: ANN001
    ) -> None:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._require_active_semester(semester_id)
        co = self._repo.get_calendar_override(override_id)
        if co is None or co.semester_id != semester_id:
            raise NotFoundError("校历覆盖不存在")
        self._repo.delete_calendar_override(co)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.calendar_override.delete",
            resource_type="calendar_override",
            resource_id=str(override_id),
            before={"date": co.date.isoformat()},
            after=None,
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()

    # ================================================================== #
    # 行政班
    # ================================================================== #
    def create_admin_class(
        self,
        actor: CurrentUser,
        body: AdministrativeClassCreateRequest,
        request_id,  # noqa: ANN001
    ) -> AdministrativeClassResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        if self._repo.get_admin_class_by_code(body.class_code) is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "行政班代码已存在")
        ac = AdministrativeClass(
            class_code=body.class_code,
            class_name=body.class_name,
            grade_year=body.grade_year,
            major_name=body.major_name,
            college=body.college,
            status=perms.RECORD_STATUS_ACTIVE,
        )
        self._repo.add(ac)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.admin_class.create",
            resource_type="administrative_class",
            resource_id=str(ac.id),
            before=None,
            after={"class_code": ac.class_code, "college": ac.college},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return AdministrativeClassResponse.model_validate(ac)

    def update_admin_class(
        self,
        actor: CurrentUser,
        class_id: int,
        body: AdministrativeClassUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> AdministrativeClassResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._validate_status(body.status)
        ac = self._repo.get_admin_class_for_update(class_id)
        if ac is None:
            raise NotFoundError("行政班不存在")
        before = {"class_name": ac.class_name, "status": ac.status, "college": ac.college}
        if body.class_name is not None:
            ac.class_name = body.class_name
        if body.grade_year is not None:
            ac.grade_year = body.grade_year
        if body.major_name is not None:
            ac.major_name = body.major_name
        if body.college is not None:
            ac.college = body.college
        if body.status is not None:
            ac.status = body.status
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.admin_class.update",
            resource_type="administrative_class",
            resource_id=str(ac.id),
            before=before,
            after={"class_name": ac.class_name, "status": ac.status, "college": ac.college},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return AdministrativeClassResponse.model_validate(ac)

    def get_admin_class(self, class_id: int) -> AdministrativeClassResponse:
        ac = self._repo.get_admin_class(class_id)
        if ac is None:
            raise NotFoundError("行政班不存在")
        return AdministrativeClassResponse.model_validate(ac)

    def list_admin_classes(
        self, params: PageParams, *, college: str | None, status: str | None, keyword: str | None
    ) -> dict:
        rows, total = self._repo.list_admin_classes(
            params, college=college, status=status, keyword=keyword
        )
        return _page([AdministrativeClassResponse.model_validate(r) for r in rows], total, params)

    # ================================================================== #
    # 学生
    # ================================================================== #
    def create_student(
        self,
        actor: CurrentUser,
        body: StudentCreateRequest,
        request_id,  # noqa: ANN001
    ) -> StudentResponse:
        self._require_actor_permission(actor.id, PermissionCode.STUDENT_MANAGE.value)
        if self._repo.get_student_by_no(body.student_no) is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学号已存在")
        if (
            body.administrative_class_id is not None
            and self._repo.get_admin_class(body.administrative_class_id) is None
        ):
            raise NotFoundError("行政班不存在")
        stu = Student(
            student_no=body.student_no,
            name=body.name,
            administrative_class_id=body.administrative_class_id,
            status=perms.RECORD_STATUS_ACTIVE,
        )
        self._repo.add(stu)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.student.create",
            resource_type="student",
            resource_id=str(stu.id),
            before=None,
            after={"student_no": stu.student_no, "name": stu.name},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return StudentResponse.model_validate(stu)

    def update_student(
        self,
        actor: CurrentUser,
        student_id: int,
        body: StudentUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> StudentResponse:
        self._require_actor_permission(actor.id, PermissionCode.STUDENT_MANAGE.value)
        self._validate_status(body.status)
        stu = self._repo.get_student_for_update(student_id)
        if stu is None:
            raise NotFoundError("学生不存在")
        before = {"name": stu.name, "class": stu.administrative_class_id, "status": stu.status}
        if body.name is not None:
            stu.name = body.name
        if body.administrative_class_id is not None:
            if self._repo.get_admin_class(body.administrative_class_id) is None:
                raise NotFoundError("行政班不存在")
            stu.administrative_class_id = body.administrative_class_id
        if body.status is not None:
            stu.status = body.status
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.student.update",
            resource_type="student",
            resource_id=str(stu.id),
            before=before,
            after={"name": stu.name, "class": stu.administrative_class_id, "status": stu.status},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return StudentResponse.model_validate(stu)

    def get_student(self, student_id: int) -> StudentResponse:
        stu = self._repo.get_student(student_id)
        if stu is None:
            raise NotFoundError("学生不存在")
        return StudentResponse.model_validate(stu)

    def list_students(
        self,
        params: PageParams,
        *,
        administrative_class_id: int | None,
        college: str | None,
        status: str | None,
        keyword: str | None,
    ) -> dict:
        rows, total = self._repo.list_students(
            params,
            administrative_class_id=administrative_class_id,
            college=college,
            status=status,
            keyword=keyword,
        )
        return _page([StudentResponse.model_validate(r) for r in rows], total, params)

    # ================================================================== #
    # 课程
    # ================================================================== #
    def create_course(
        self,
        actor: CurrentUser,
        body: CourseCreateRequest,
        request_id,  # noqa: ANN001
    ) -> CourseResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        if self._repo.get_course_by_code(body.course_code) is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "课程代码已存在")
        c = Course(
            course_code=body.course_code,
            course_name=body.course_name,
            status=perms.RECORD_STATUS_ACTIVE,
        )
        self._repo.add(c)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.course.create",
            resource_type="course",
            resource_id=str(c.id),
            before=None,
            after={"course_code": c.course_code, "course_name": c.course_name},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return CourseResponse.model_validate(c)

    def update_course(
        self,
        actor: CurrentUser,
        course_id: int,
        body: CourseUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> CourseResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._validate_status(body.status)
        c = self._repo.get_course_for_update(course_id)
        if c is None:
            raise NotFoundError("课程不存在")
        before = {"course_name": c.course_name, "status": c.status}
        if body.course_name is not None:
            c.course_name = body.course_name
        if body.status is not None:
            c.status = body.status
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.course.update",
            resource_type="course",
            resource_id=str(c.id),
            before=before,
            after={"course_name": c.course_name, "status": c.status},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return CourseResponse.model_validate(c)

    def get_course(self, course_id: int) -> CourseResponse:
        c = self._repo.get_course(course_id)
        if c is None:
            raise NotFoundError("课程不存在")
        return CourseResponse.model_validate(c)

    def list_courses(self, params: PageParams, *, status: str | None, keyword: str | None) -> dict:
        rows, total = self._repo.list_courses(params, status=status, keyword=keyword)
        return _page([CourseResponse.model_validate(r) for r in rows], total, params)

    # ================================================================== #
    # 教学班（结构）
    # ================================================================== #
    def create_teaching_class(
        self,
        actor: CurrentUser,
        body: TeachingClassCreateRequest,
        request_id,  # noqa: ANN001
    ) -> TeachingClassResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        sem = self._require_active_semester(body.semester_id)
        if self._repo.get_course(body.course_id) is None:
            raise NotFoundError("课程不存在")
        if (
            self._repo.get_teaching_class_by_key(sem.id, body.course_id, body.class_code)
            is not None
        ):
            raise ConflictError(ErrorCode.STATE_CONFLICT, "同学期同课程同班码的教学班已存在")
        tc = TeachingClass(
            semester_id=sem.id,
            course_id=body.course_id,
            class_code=body.class_code,
            class_name=body.class_name,
            status=perms.RECORD_STATUS_ACTIVE,
        )
        self._repo.add(tc)
        self._repo.flush()
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.teaching_class.create",
            resource_type="teaching_class",
            resource_id=str(tc.id),
            before=None,
            after={
                "semester_id": tc.semester_id,
                "course_id": tc.course_id,
                "class_name": tc.class_name,
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return TeachingClassResponse.model_validate(tc)

    def update_teaching_class(
        self,
        actor: CurrentUser,
        tc_id: int,
        body: TeachingClassUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> TeachingClassResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._validate_status(body.status)
        tc = self._repo.get_teaching_class_for_update(tc_id)
        if tc is None:
            raise NotFoundError("教学班不存在")
        self._require_active_semester(tc.semester_id)
        before = {"class_name": tc.class_name, "status": tc.status}
        if body.class_name is not None:
            tc.class_name = body.class_name
        if body.class_code is not None:
            tc.class_code = body.class_code
        if body.status is not None:
            tc.status = body.status
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.teaching_class.update",
            resource_type="teaching_class",
            resource_id=str(tc.id),
            before=before,
            after={"class_name": tc.class_name, "status": tc.status},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return TeachingClassResponse.model_validate(tc)

    def get_teaching_class(self, tc_id: int) -> TeachingClassResponse:
        tc = self._repo.get_teaching_class(tc_id)
        if tc is None:
            raise NotFoundError("教学班不存在")
        return TeachingClassResponse.model_validate(tc)

    def list_teaching_classes(
        self,
        params: PageParams,
        *,
        semester_id: int | None,
        course_id: int | None,
        status: str | None,
    ) -> dict:
        rows, total = self._repo.list_teaching_classes(
            params, semester_id=semester_id, course_id=course_id, status=status
        )
        return _page([TeachingClassResponse.model_validate(r) for r in rows], total, params)

    # ---- 教学班名单（roster，受 student.manage 守卫）----
    def replace_roster(
        self,
        actor: CurrentUser,
        tc_id: int,
        student_ids: Sequence[int],
        reason,
        request_id,  # noqa: ANN001
    ) -> list[StudentResponse]:
        self._require_actor_permission(actor.id, PermissionCode.STUDENT_MANAGE.value)
        tc = self._repo.get_teaching_class_for_update(tc_id)
        if tc is None:
            raise NotFoundError("教学班不存在")
        self._require_active_semester(tc.semester_id)
        uniq = [int(s) for s in dict.fromkeys(student_ids)]
        if uniq:
            found = {s.id for s in self._repo.get_students_by_ids(uniq)}
            missing = sorted(set(uniq) - found)
            if missing:
                raise NotFoundError(f"以下学生不存在：{missing}")
        before_ids = [s.id for s in self._repo.get_roster_students(tc_id)]
        self._repo.set_roster(tc_id, uniq)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.teaching_class.roster.replace",
            resource_type="teaching_class",
            resource_id=str(tc_id),
            before={"student_count": len(before_ids)},
            after={"student_count": len(uniq)},
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()
        return [StudentResponse.model_validate(s) for s in self._repo.get_roster_students(tc_id)]

    def list_roster(self, tc_id: int) -> list[StudentResponse]:
        if self._repo.get_teaching_class(tc_id) is None:
            raise NotFoundError("教学班不存在")
        return [StudentResponse.model_validate(s) for s in self._repo.get_roster_students(tc_id)]

    # ================================================================== #
    # 课表
    # ================================================================== #
    def _validate_schedule_periods(
        self, start: int, end: int, weeks: Sequence[int], total_weeks: int
    ) -> None:
        if end < start:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "结束大节不得早于开始大节",
                http_status=422,
                field_errors={"end_period": "must_be_ge_start_period"},
            )
        bad = [w for w in weeks if w < 1 or w > total_weeks]
        if bad:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"生效周次超出学期范围(1..{total_weeks})",
                http_status=422,
                field_errors={"weeks": bad},
            )

    def create_schedule(
        self,
        actor: CurrentUser,
        body: CourseScheduleCreateRequest,
        request_id,  # noqa: ANN001
    ) -> CourseScheduleResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        tc = self._repo.get_teaching_class_for_update(body.teaching_class_id)
        if tc is None:
            raise NotFoundError("教学班不存在")
        sem = self._require_active_semester(tc.semester_id)
        self._validate_schedule_periods(
            body.start_period, body.end_period, body.weeks, sem.total_weeks
        )
        s = CourseSchedule(
            semester_id=sem.id,
            teaching_class_id=tc.id,
            weekday=body.weekday,
            start_period=body.start_period,
            end_period=body.end_period,
            classroom=body.classroom,
            status=perms.RECORD_STATUS_ACTIVE,
        )
        self._repo.add(s)
        self._repo.flush()
        self._repo.set_schedule_weeks(s, body.weeks)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.course_schedule.create",
            resource_type="course_schedule",
            resource_id=str(s.id),
            before=None,
            after={
                "teaching_class_id": s.teaching_class_id,
                "weekday": s.weekday,
                "start_period": s.start_period,
                "end_period": s.end_period,
                "week_count": len(set(body.weeks)),
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(s)
        return _sched_dto(s)

    def update_schedule(
        self,
        actor: CurrentUser,
        schedule_id: int,
        body: CourseScheduleUpdateRequest,
        request_id,  # noqa: ANN001
    ) -> CourseScheduleResponse:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        self._validate_status(body.status)
        s = self._repo.get_schedule_for_update(schedule_id)
        if s is None:
            raise NotFoundError("课表条目不存在")
        sem = self._require_active_semester(s.semester_id)
        start = body.start_period if body.start_period is not None else s.start_period
        end = body.end_period if body.end_period is not None else s.end_period
        weeks = body.weeks if body.weeks is not None else [w.week_no for w in s.weeks]
        self._validate_schedule_periods(start, end, weeks, sem.total_weeks)
        before = {
            "weekday": s.weekday,
            "start_period": s.start_period,
            "end_period": s.end_period,
            "status": s.status,
            "week_count": len(s.weeks),
        }
        if body.weekday is not None:
            s.weekday = body.weekday
        if body.start_period is not None:
            s.start_period = body.start_period
        if body.end_period is not None:
            s.end_period = body.end_period
        if body.classroom is not None:
            s.classroom = body.classroom
        if body.status is not None:
            s.status = body.status
        if body.weeks is not None:
            self._repo.set_schedule_weeks(s, weeks)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.course_schedule.update",
            resource_type="course_schedule",
            resource_id=str(s.id),
            before=before,
            after={
                "weekday": s.weekday,
                "start_period": s.start_period,
                "end_period": s.end_period,
                "status": s.status,
                "week_count": len(list(s.weeks)),
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(s)
        return _sched_dto(s)

    def get_schedule(self, schedule_id: int) -> CourseScheduleResponse:
        s = self._repo.get_schedule(schedule_id)
        if s is None:
            raise NotFoundError("课表条目不存在")
        return _sched_dto(s)

    def list_schedules(
        self,
        params: PageParams,
        *,
        semester_id: int | None,
        teaching_class_id: int | None,
        status: str | None,
    ) -> dict:
        rows, total = self._repo.list_schedules(
            params, semester_id=semester_id, teaching_class_id=teaching_class_id, status=status
        )
        return _page([_sched_dto(r) for r in rows], total, params)

    def delete_schedule(
        self,
        actor: CurrentUser,
        schedule_id: int,
        reason,
        request_id,  # noqa: ANN001
    ) -> None:
        self._require_actor_permission(actor.id, PermissionCode.ACADEMIC_MANAGE.value)
        s = self._repo.get_schedule_for_update(schedule_id)
        if s is None:
            raise NotFoundError("课表条目不存在")
        self._require_active_semester(s.semester_id)
        snapshot = {"teaching_class_id": s.teaching_class_id, "weekday": s.weekday}
        self._repo.delete_schedule(s)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.course_schedule.delete",
            resource_type="course_schedule",
            resource_id=str(schedule_id),
            before=snapshot,
            after=None,
            reason=reason,
            request_id=request_id,
        )
        self._session.commit()

    # ================================================================== #
    # 志愿者学期资格（含 VOLUNTEER 自动身份维护）
    # ================================================================== #
    def _grant_volunteer_role(self, student_id: int) -> bool:
        """学生若已绑定账号则确保其持有 VOLUNTEER 角色（系统自动身份）。返回是否新授予。"""
        acct = self._session.execute(
            select(UserAccount).where(UserAccount.student_id == student_id)
        ).scalar_one_or_none()
        if acct is None:
            return False
        if RoleCode.VOLUNTEER.value in self._identity.list_role_codes(acct.id):
            return False
        role = self._identity.get_or_create_role(RoleCode.VOLUNTEER.value, RoleCode.VOLUNTEER.value)
        self._identity.grant_role(acct.id, role.id)
        acct.lock_version += 1
        return True

    def upsert_volunteer_qualification(
        self,
        actor: CurrentUser,
        body: VolunteerQualificationUpsertRequest,
        request_id,  # noqa: ANN001
    ) -> VolunteerQualificationResponse:
        self._require_actor_permission(actor.id, PermissionCode.VOLUNTEER_MANAGE.value)
        sem = self._require_active_semester(body.semester_id)
        stu = self._repo.get_student(body.student_id)
        if stu is None:
            raise NotFoundError("学生不存在")
        existing = self._repo.get_volunteer_qualification_by_sem_student(sem.id, body.student_id)
        created = existing is None
        vq = (
            existing
            if existing is not None
            else VolunteerQualification(
                semester_id=sem.id,
                student_id=body.student_id,
                enabled=body.enabled,
                created_by=actor.id,
            )
        )
        granted_role = False
        if created:
            self._repo.add(vq)
            self._repo.flush()
        else:
            vq.enabled = body.enabled
            self._repo.flush()
        # 首次获得有效资格：同事务自动维护 VOLUNTEER 身份（PERMISSIONS.md 1.4/1.5）。
        # 停用不回收角色：资格是逐学期闸口，停用即时禁止提交由提交阶段判定，历史只读保留。
        if body.enabled:
            granted_role = self._grant_volunteer_role(body.student_id)
        self._record_audit(
            actor_user_id=actor.id,
            action="academic.volunteer_qualification.upsert",
            resource_type="volunteer_qualification",
            resource_id=str(vq.id),
            before=None if created else {"enabled": not body.enabled},
            after={
                "semester_id": vq.semester_id,
                "student_id": vq.student_id,
                "enabled": vq.enabled,
                "volunteer_role_granted": granted_role,
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return VolunteerQualificationResponse.model_validate(vq)

    def list_volunteer_qualifications(
        self, params: PageParams, *, semester_id: int | None, enabled: bool | None
    ) -> dict:
        rows, total = self._repo.list_volunteer_qualifications(
            params, semester_id=semester_id, enabled=enabled
        )
        return _page(
            [VolunteerQualificationResponse.model_validate(r) for r in rows], total, params
        )
