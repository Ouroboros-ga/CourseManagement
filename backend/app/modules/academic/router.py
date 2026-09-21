"""基础数据路由：处理 HTTP、装配依赖与封装响应，业务流程交给 Service（技术方案第 5 节）。

前缀在 main.py 统一挂载为 /api/v1/academic。守卫沿用集中 PermissionCode：
academic / student / volunteer 各自的 read/manage 对应不同资源的读/写。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.core.permissions import PermissionCode
from app.modules.academic.schemas import (
    AdministrativeClassCreateRequest,
    AdministrativeClassUpdateRequest,
    CalendarOverrideCreateRequest,
    CourseCreateRequest,
    CourseScheduleCreateRequest,
    CourseScheduleUpdateRequest,
    CourseUpdateRequest,
    PeriodDefinitionUpsertRequest,
    RosterReplaceRequest,
    SemesterCreateRequest,
    SemesterUpdateRequest,
    StudentCreateRequest,
    StudentUpdateRequest,
    TeachingClassCreateRequest,
    TeachingClassUpdateRequest,
    VolunteerQualificationUpsertRequest,
)
from app.modules.academic.service import AcademicService
from app.modules.identity.deps import CurrentUser, require_permission

router = APIRouter(tags=["academic"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AcademicService:
    return AcademicService(db)


ServiceDep = Annotated[AcademicService, Depends(get_service)]

# ---- 功能守卫别名 ----
AcademicReadDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.ACADEMIC_READ.value))
]
AcademicManageDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.ACADEMIC_MANAGE.value))
]
StudentReadDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.STUDENT_READ.value))
]
StudentManageDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.STUDENT_MANAGE.value))
]
VolunteerReadDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.VOLUNTEER_READ.value))
]
VolunteerManageDep = Annotated[
    CurrentUser, Depends(require_permission(PermissionCode.VOLUNTEER_MANAGE.value))
]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# =========================================================================== #
# 学期
# =========================================================================== #
@router.post("/semesters")
def create_semester(
    body: SemesterCreateRequest, actor: AcademicManageDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.create_semester(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/semesters/{semester_id}")
def update_semester(
    semester_id: int,
    body: SemesterUpdateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_semester(actor, semester_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/semesters/{semester_id}")
def get_semester(
    semester_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_semester(semester_id).model_dump(), _rid(request))


@router.get("/semesters")
def list_semesters(
    actor: AcademicReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    return success(service.list_semesters(params, status=status), _rid(request))


# =========================================================================== #
# 节次定义
# =========================================================================== #
@router.put("/semesters/{semester_id}/period-definitions/{period_no}")
def upsert_period_definition(
    semester_id: int,
    period_no: int,
    body: PeriodDefinitionUpsertRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    # 路径 period_no 权威覆盖请求体，避免路径/体不一致。
    body.period_no = period_no
    result = service.upsert_period_definition(actor, semester_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/semesters/{semester_id}/period-definitions")
def list_period_definitions(
    semester_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    items = [r.model_dump() for r in service.list_period_definitions(semester_id)]
    return success({"items": items}, _rid(request))


@router.delete("/semesters/{semester_id}/period-definitions/{period_id}", status_code=204)
def delete_period_definition(
    semester_id: int,
    period_id: int,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
    reason: Annotated[str | None, Query(max_length=512)] = None,
) -> Response:
    service.delete_period_definition(actor, semester_id, period_id, reason, _rid(request))
    return Response(status_code=204)


# =========================================================================== #
# 校历覆盖
# =========================================================================== #
@router.post("/semesters/{semester_id}/calendar-overrides")
def create_calendar_override(
    semester_id: int,
    body: CalendarOverrideCreateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_calendar_override(actor, semester_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/semesters/{semester_id}/calendar-overrides")
def list_calendar_overrides(
    semester_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    items = [r.model_dump() for r in service.list_calendar_overrides(semester_id)]
    return success({"items": items}, _rid(request))


@router.delete("/semesters/{semester_id}/calendar-overrides/{override_id}", status_code=204)
def delete_calendar_override(
    semester_id: int,
    override_id: int,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
    reason: Annotated[str | None, Query(max_length=512)] = None,
) -> Response:
    service.delete_calendar_override(actor, semester_id, override_id, reason, _rid(request))
    return Response(status_code=204)


# =========================================================================== #
# 行政班
# =========================================================================== #
@router.post("/administrative-classes")
def create_admin_class(
    body: AdministrativeClassCreateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_admin_class(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/administrative-classes/{class_id}")
def update_admin_class(
    class_id: int,
    body: AdministrativeClassUpdateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_admin_class(actor, class_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/administrative-classes/{class_id}")
def get_admin_class(
    class_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_admin_class(class_id).model_dump(), _rid(request))


@router.get("/administrative-classes")
def list_admin_classes(
    actor: AcademicReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    college: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    return success(
        service.list_admin_classes(params, college=college, status=status, keyword=keyword),
        _rid(request),
    )


# =========================================================================== #
# 学生
# =========================================================================== #
@router.post("/students")
def create_student(
    body: StudentCreateRequest,
    actor: StudentManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_student(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/students/{student_id}")
def update_student(
    student_id: int,
    body: StudentUpdateRequest,
    actor: StudentManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_student(actor, student_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/students/{student_id}")
def get_student(
    student_id: int, actor: StudentReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_student(student_id).model_dump(), _rid(request))


@router.get("/students")
def list_students(
    actor: StudentReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    administrative_class_id: Annotated[int | None, Query(ge=1)] = None,
    college: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    return success(
        service.list_students(
            params,
            administrative_class_id=administrative_class_id,
            college=college,
            status=status,
            keyword=keyword,
        ),
        _rid(request),
    )


# =========================================================================== #
# 课程
# =========================================================================== #
@router.post("/courses")
def create_course(
    body: CourseCreateRequest, actor: AcademicManageDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.create_course(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/courses/{course_id}")
def update_course(
    course_id: int,
    body: CourseUpdateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_course(actor, course_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/courses/{course_id}")
def get_course(
    course_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_course(course_id).model_dump(), _rid(request))


@router.get("/courses")
def list_courses(
    actor: AcademicReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    status: Annotated[str | None, Query(max_length=16)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    return success(service.list_courses(params, status=status, keyword=keyword), _rid(request))


# =========================================================================== #
# 教学班 + 名单
# =========================================================================== #
@router.post("/teaching-classes")
def create_teaching_class(
    body: TeachingClassCreateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_teaching_class(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/teaching-classes/{tc_id}")
def update_teaching_class(
    tc_id: int,
    body: TeachingClassUpdateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_teaching_class(actor, tc_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/teaching-classes/{tc_id}")
def get_teaching_class(
    tc_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_teaching_class(tc_id).model_dump(), _rid(request))


@router.get("/teaching-classes")
def list_teaching_classes(
    actor: AcademicReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    course_id: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    return success(
        service.list_teaching_classes(
            params, semester_id=semester_id, course_id=course_id, status=status
        ),
        _rid(request),
    )


@router.get("/teaching-classes/{tc_id}/students")
def list_roster(
    tc_id: int, actor: StudentReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    items = [r.model_dump() for r in service.list_roster(tc_id)]
    return success({"items": items}, _rid(request))


@router.put("/teaching-classes/{tc_id}/students")
def replace_roster(
    tc_id: int,
    body: RosterReplaceRequest,
    actor: StudentManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    items = [
        r.model_dump()
        for r in service.replace_roster(actor, tc_id, body.student_ids, body.reason, _rid(request))
    ]
    return success({"items": items}, _rid(request))


# =========================================================================== #
# 课表
# =========================================================================== #
@router.post("/course-schedules")
def create_schedule(
    body: CourseScheduleCreateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_schedule(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/course-schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    body: CourseScheduleUpdateRequest,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_schedule(actor, schedule_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/course-schedules/{schedule_id}")
def get_schedule(
    schedule_id: int, actor: AcademicReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    return success(service.get_schedule(schedule_id).model_dump(), _rid(request))


@router.get("/course-schedules")
def list_schedules(
    actor: AcademicReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    teaching_class_id: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    return success(
        service.list_schedules(
            params, semester_id=semester_id, teaching_class_id=teaching_class_id, status=status
        ),
        _rid(request),
    )


@router.delete("/course-schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int,
    actor: AcademicManageDep,
    service: ServiceDep,
    request: Request,
    reason: Annotated[str | None, Query(max_length=512)] = None,
) -> Response:
    service.delete_schedule(actor, schedule_id, reason, _rid(request))
    return Response(status_code=204)


# =========================================================================== #
# 志愿者学期资格
# =========================================================================== #
@router.put("/volunteer-qualifications")
def upsert_volunteer_qualification(
    body: VolunteerQualificationUpsertRequest,
    actor: VolunteerManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.upsert_volunteer_qualification(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.get("/volunteer-qualifications")
def list_volunteer_qualifications(
    actor: VolunteerReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    return success(
        service.list_volunteer_qualifications(params, semester_id=semester_id, enabled=enabled),
        _rid(request),
    )
