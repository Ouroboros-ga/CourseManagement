"""查课任务与排班路由（Wave 2）：任务预览 / 生成 + 读取（列表 / 详情 / 本人 / 名单）。

前缀在 main.py 挂载为 /api/v1/inspection。功能守卫沿用集中 PermissionCode：
- 预览 / 生成：inspection.generate（路由早拦，Service 事务内纵深复核）；
- 列表 / 详情 / 本人任务：inspection.read；
- 名单读取：inspection.roster.read（并叠加任务可见性范围，防越权读他人受派任务名单）。
数据范围（管理全部可见 / 志愿者仅本人受派）在 Service 依 resolve_scope 构造谓词统一施加。
"""

from __future__ import annotations

from datetime import date as date_
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.core.permissions import PermissionCode
from app.modules.identity.deps import CurrentUserDep, require_permission
from app.modules.inspection.schemas import (
    AssignmentSetRequest,
    AutoAssignRequest,
    ChangeRequestCreateRequest,
    ChangeRequestReviewRequest,
    CourseOccurrenceScope,
    DeadlineDayUpdateRequest,
    DeadlineSettleRequest,
    ExpectedCountUpdateRequest,
    InspectionGenerateRequest,
    InspectionTaskUpdateRequest,
    SmartSampleRequest,
    ReviewStatusLiteral,
    RosterVersionCreateRequest,
    SubmissionCreateRequest,
    SubmissionReviewRequest,
    TaskCancelRequest,
)
from app.modules.inspection.service import InspectionService

router = APIRouter(tags=["inspection"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> InspectionService:
    return InspectionService(db)


ServiceDep = Annotated[InspectionService, Depends(get_service)]

InspectionReadDep = Annotated[
    CurrentUserDep, Depends(require_permission(PermissionCode.INSPECTION_READ.value))
]
InspectionGenerateDep = Annotated[
    CurrentUserDep, Depends(require_permission(PermissionCode.INSPECTION_GENERATE.value))
]
RosterReadDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.INSPECTION_ROSTER_READ.value)),
]
AssignmentManageDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ASSIGNMENT_MANAGE.value)),
]
ChangeRequestDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ASSIGNMENT_CHANGE_REQUEST.value)),
]
ChangeReviewDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ASSIGNMENT_CHANGE_REVIEW.value)),
]
InspectionCancelDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.INSPECTION_CANCEL.value)),
]
RosterManageDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.INSPECTION_ROSTER_MANAGE.value)),
]
DeadlineReadDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.SUBMISSION_DEADLINE_READ.value)),
]
DeadlineManageDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.SUBMISSION_DEADLINE_MANAGE.value)),
]
SubmissionCreateDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.SUBMISSION_CREATE.value)),
]
SubmissionReadDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.SUBMISSION_READ.value)),
]
SubmissionReviewDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.SUBMISSION_REVIEW.value)),
]
ExpectedCountAdjustDep = Annotated[
    CurrentUserDep,
    Depends(require_permission(PermissionCode.ATTENDANCE_EXPECTED_COUNT_ADJUST.value)),
]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ---- 生成预览 / 生成 ----
@router.get("/inspection-course-occurrences")
def get_course_occurrences(
    actor: InspectionGenerateDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
    date_from: date_,
    date_to: date_,
    teaching_class_ids: Annotated[list[int] | None, Query(max_length=2000)] = None,
    administrative_class_id: Annotated[int | None, Query(ge=1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 200,
    require_photo: bool = False,
) -> dict[str, object]:
    from sqlalchemy import select
    from app.modules.inspection.course_occurrences import list_occurrences

    if not 0 <= (date_to - date_from).days < 31:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "日期范围须为1至31天", http_status=422,
        )
    service._require(actor.id, PermissionCode.INSPECTION_GENERATE.value)
    semester = service._get_active_semester_read(semester_id)

    if administrative_class_id is not None:
        from app.modules.academic.models import Student, TeachingClass, TeachingClassStudent

        resolved_tc_ids = list(
            service._session.execute(
                select(TeachingClass.id).where(
                    TeachingClass.semester_id == semester.id,
                    TeachingClass.status == "ACTIVE",
                    select(TeachingClassStudent.student_id)
                    .join(Student, Student.id == TeachingClassStudent.student_id)
                    .where(
                        TeachingClassStudent.teaching_class_id == TeachingClass.id,
                        Student.administrative_class_id == administrative_class_id,
                        Student.status == "ACTIVE",
                    )
                    .exists(),
                )
            )
            .scalars()
            .all()
        )
    elif teaching_class_ids:
        if any(i < 1 for i in teaching_class_ids):
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "教学班ID须为正数", http_status=422,
            )
        resolved_tc_ids = teaching_class_ids
    else:
        from app.modules.academic.models import TeachingClass

        resolved_tc_ids = list(
            service._session.execute(
                select(TeachingClass.id).where(
                    TeachingClass.semester_id == semester.id,
                    TeachingClass.status == "ACTIVE",
                )
            )
            .scalars()
            .all()
        )

    if not resolved_tc_ids:
        return success(
            {
                "items": [],
                "page": page,
                "page_size": page_size,
                "total": 0,
                "selection_revision": "empty",
                "selection_scope": {
                    "date_from": date_from,
                    "date_to": date_to,
                    "teaching_class_ids": [],
                    "require_photo": require_photo,
                },
            },
            _rid(request),
        )

    scope = CourseOccurrenceScope(
        date_from=date_from,
        date_to=date_to,
        teaching_class_ids=resolved_tc_ids,
        require_photo=require_photo,
    )
    return success(
        list_occurrences(service, semester, scope, page=page, page_size=page_size),
        _rid(request),
    )


@router.post("/inspection-course-occurrences/smart-sample")
def smart_sample_course_occurrences(
    body: SmartSampleRequest,
    actor: InspectionGenerateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    from app.modules.inspection.course_occurrences import smart_sample_occurrences

    service._require(actor.id, PermissionCode.INSPECTION_GENERATE.value)
    semester = service._get_active_semester_read(body.semester_id)
    result = smart_sample_occurrences(service, semester, body)
    return success(result, _rid(request))


@router.post("/inspection-tasks/preview")
def preview_inspection_tasks(
    body: InspectionGenerateRequest,
    actor: InspectionGenerateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.preview(actor, body)
    return success(result.model_dump(), _rid(request))


@router.post("/inspection-tasks/generate")
def generate_inspection_tasks(
    body: InspectionGenerateRequest,
    actor: InspectionGenerateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.generate(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.post("/inspection-tasks/{task_id}/restore")
def restore_inspection_task(task_id: int, body: TaskCancelRequest,
                            actor: InspectionGenerateDep, service: ServiceDep,
                            request: Request) -> dict[str, object]:
    from app.modules.inspection.restore_service import restore_task

    return success(restore_task(service, actor, task_id, body, _rid(request)).model_dump(),
                   _rid(request))


# ---- 本人受派任务（须在 /{task_id} 之前声明，避免 me 被当作 id 路径吞掉）----
@router.get("/me/inspection-tasks")
def list_my_inspection_tasks(
    actor: InspectionReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    include_canceled: Annotated[bool, Query()] = True,
) -> dict[str, object]:
    data = service.my_tasks(actor, params, include_canceled=include_canceled)
    return success(data, _rid(request))


# ---- 任务列表 / 详情 ----
@router.get("/inspection-tasks")
def list_inspection_tasks(
    actor: InspectionReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    inspection_date: Annotated[date_ | None, Query()] = None,
    week_no: Annotated[int | None, Query(ge=1, le=60)] = None,
    inspection_type: Annotated[str | None, Query(max_length=16)] = None,
    teaching_class_id: Annotated[int | None, Query(ge=1)] = None,
    administrative_class_id: Annotated[int | None, Query(ge=1)] = None,
    include_canceled: Annotated[bool, Query()] = True,
) -> dict[str, object]:
    return success(
        service.list_tasks(
            actor,
            params,
            semester_id=semester_id,
            inspection_date=inspection_date,
            week_no=week_no,
            inspection_type=inspection_type,
            teaching_class_id=teaching_class_id,
            administrative_class_id=administrative_class_id,
            include_canceled=include_canceled,
        ),
        _rid(request),
    )


@router.get("/inspection-tasks/{task_id}")
def get_inspection_task(
    task_id: int, actor: InspectionReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.get_task(actor, task_id)
    return success(result.model_dump(), _rid(request))


# ---- 任务名单（roster.read + 任务可见性范围）----
@router.get("/inspection-tasks/{task_id}/students")
def get_inspection_task_roster(
    task_id: int,
    actor: RosterReadDep,
    service: ServiceDep,
    request: Request,
    roster_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    result = service.get_roster(actor, task_id, roster_version)
    return success(result.model_dump(), _rid(request))


# ---- 排班：自动分配（assignment.manage）----
@router.post("/assignments/auto")
def auto_assign(
    body: AutoAssignRequest,
    actor: AssignmentManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.auto_assign(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 人工分配 / 改派（assignment.manage）----
@router.put("/inspection-tasks/{task_id}/assignment")
def set_task_assignment(
    task_id: int,
    body: AssignmentSetRequest,
    actor: AssignmentManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.assign_manual(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 调班申请：志愿者对本人当前受派发起（assignment.change_request）----
@router.post("/assignment-change-requests")
def create_change_request(
    body: ChangeRequestCreateRequest,
    actor: ChangeRequestDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_change_request(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 本人调班申请（须在 /{request_id} 之前声明，避免 me 被当作 id 路径吞掉）----
@router.get("/me/assignment-change-requests")
def list_my_change_requests(
    actor: ChangeRequestDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    data = service.list_my_change_requests(actor, params, status=status)
    return success(data, _rid(request))


# ---- 管理视图：读取全部调班申请（assignment.change_review）----
@router.get("/assignment-change-requests")
def list_change_requests(
    actor: ChangeReviewDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, object]:
    data = service.list_change_requests(actor, params, status=status)
    return success(data, _rid(request))


# ---- 处理调班申请：通过 / 驳回（assignment.change_review）----
@router.post("/assignment-change-requests/{request_id}/review")
def review_change_request(
    request_id: int,
    body: ChangeRequestReviewRequest,
    actor: ChangeReviewDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.review_change_request(actor, request_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ================================================================== #
# Wave 3c：取消 / 名单改版 / 截止时间配置 / 截止结算
# ================================================================== #
# ---- 取消任务（inspection.cancel）----
@router.post("/inspection-tasks/{task_id}/cancel")
def cancel_inspection_task(
    task_id: int,
    body: TaskCancelRequest,
    actor: InspectionCancelDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.cancel_task(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 名单改版：生成新版本并冻结快照（inspection.roster.manage）----
@router.post("/inspection-tasks/{task_id}/roster-versions")
def create_roster_version(
    task_id: int,
    body: RosterVersionCreateRequest,
    actor: RosterManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_roster_version(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 名单版本历史（inspection.roster.read + 任务可见性）----
@router.get("/inspection-tasks/{task_id}/roster-versions")
def list_roster_versions(
    task_id: int, actor: RosterReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.list_roster_versions(actor, task_id)
    return success([r.model_dump() for r in result], _rid(request))


# ---- 全局默认截止时刻（submission_deadline.read，只读配置反射）----
@router.get("/submission-deadlines/default")
def get_default_deadline(
    actor: DeadlineReadDep, service: ServiceDep, request: Request
) -> dict[str, object]:
    result = service.get_default_deadline(actor)
    return success(result.model_dump(), _rid(request))


# ---- 某学期日截止列表（可按日期范围过滤）----
@router.get("/submission-deadlines/days")
def list_deadline_days(
    actor: DeadlineReadDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
    date_from: Annotated[date_ | None, Query()] = None,
    date_to: Annotated[date_ | None, Query()] = None,
) -> dict[str, object]:
    result = service.list_deadline_days(
        actor, semester_id=semester_id, date_from=date_from, date_to=date_to
    )
    return success([r.model_dump() for r in result], _rid(request))


# ---- 改指定查课日截止（submission_deadline.manage）：须在 /days/{date} 之前？
# 路由靠方法与子路径区分，无冲突。放 GET/PUT /days/{inspection_date}。
@router.get("/submission-deadlines/days/{inspection_date}")
def get_deadline_day(
    inspection_date: date_,
    actor: DeadlineReadDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
) -> dict[str, object]:
    result = service.get_deadline_day(actor, semester_id, inspection_date)
    return success(result.model_dump(), _rid(request))


@router.get("/submission-deadlines/days/{inspection_date}/versions")
def list_deadline_day_versions(
    inspection_date: date_,
    actor: DeadlineReadDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
) -> dict[str, object]:
    result = service.list_deadline_day_versions(actor, semester_id, inspection_date)
    return success([r.model_dump() for r in result], _rid(request))


@router.put("/submission-deadlines/days/{inspection_date}")
def update_deadline_day(
    inspection_date: date_,
    body: DeadlineDayUpdateRequest,
    actor: DeadlineManageDep,
    service: ServiceDep,
    request: Request,
    semester_id: Annotated[int, Query(ge=1)],
) -> dict[str, object]:
    result = service.update_deadline_day(
        actor, semester_id, inspection_date, body, _rid(request)
    )
    return success(result.model_dump(), _rid(request))


# ---- 有界同步结算到期任务的截止时考核快照（submission_deadline.manage）----
@router.post("/submission-deadlines/settle")
def settle_deadlines(
    body: DeadlineSettleRequest,
    actor: DeadlineManageDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.settle_deadline(actor, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ================================================================== #
# Wave P5c：查课提交（志愿者本人受派任务提交结果 + 本人历史读取）
# ================================================================== #
# ---- 提交查课结果（submission.create，仅本人当前受派任务，Service 内纵深校验）----
@router.post("/inspection-tasks/{task_id}/submissions")
def create_inspection_submission(
    task_id: int,
    body: SubmissionCreateRequest,
    actor: SubmissionCreateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.create_submission(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 本人提交历史（submission.read，强制本人范围；须在 /{id} 之前声明）----
@router.get("/me/submissions")
def list_my_submissions(
    actor: SubmissionReadDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    task_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    data = service.list_my_submissions(actor, params, task_id=task_id)
    return success(data, _rid(request))


# ---- 本人单条提交（submission.read，非本人统一 404 防枚举）----
@router.get("/submissions/{submission_id}")
def get_my_submission(
    submission_id: int,
    actor: SubmissionReadDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.get_my_submission(actor, submission_id)
    return success(result.model_dump(), _rid(request))


# ================================================================== #
# Wave P5d：提交审核（通过据名单版本生成考勤 / 驳回保留原事实）+ 应到人数调整
# ================================================================== #
@router.get("/management/submissions")
def list_management_submissions(
    actor: SubmissionReviewDep,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    semester_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: date_ | None = None,
    date_to: date_ | None = None,
    task_id: Annotated[int | None, Query(ge=1)] = None,
    review_status: ReviewStatusLiteral | None = None,
) -> dict[str, object]:
    data = service.list_management_submissions(
        actor,
        params,
        semester_id=semester_id,
        date_from=date_from,
        date_to=date_to,
        task_id=task_id,
        review_status=review_status,
    )
    return success(data, _rid(request))


@router.get("/management/submissions/{submission_id}")
def get_management_submission(
    submission_id: int,
    actor: SubmissionReviewDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.get_management_submission(actor, submission_id)
    return success(result.model_dump(), _rid(request))


# ---- 审核待审核提交（submission.review，管理人员）----
@router.post("/submissions/{submission_id}/review")
def review_submission(
    submission_id: int,
    body: SubmissionReviewRequest,
    actor: SubmissionReviewDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.review_submission(actor, submission_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


# ---- 人工调整任务当前应到人数（attendance.expected_count_adjust，保留初始快照与历史）----
@router.patch("/inspection-tasks/{task_id}/expected-count")
def update_expected_count(
    task_id: int,
    body: ExpectedCountUpdateRequest,
    actor: ExpectedCountAdjustDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    result = service.update_expected_count(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))


@router.patch("/inspection-tasks/{task_id}")
def update_inspection_task(
    task_id: int,
    body: InspectionTaskUpdateRequest,
    actor: InspectionGenerateDep,
    service: ServiceDep,
    request: Request,
) -> dict[str, object]:
    """修改查课任务（教室地点/节次/课程名）（方式 A）。"""
    result = service.update_task_schedule_info(actor, task_id, body, _rid(request))
    return success(result.model_dump(), _rid(request))
