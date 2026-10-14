"""学籍与老师数据交接入口，业务权限、范围与事务由 Service 校验。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.modules.academic.audience_service import AudienceService
from app.modules.academic.college_service import CollegeService
from app.modules.academic.enrollment_schemas import (
    AudienceRequest,
    CollegeCreateRequest,
    EnrollmentChangeRequest,
    ManagerFunctionsRequest,
    TaskHandoffReview,
    TeacherCollegeRequest,
    VersionRequest,
)
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.identity.deps import CurrentUserDep
from app.modules.importer.student_data_service import StudentDataPreviewRequest, StudentDataService

router = APIRouter(tags=["academic-lifecycle"])
Database = Annotated[Session, Depends(get_db)]


@router.get("/enrollment-handoff/tasks")
def handoff_tasks(actor: CurrentUserDep, db: Database, request: Request):
    cid = request.path_params.get("cid")
    return success(EnrollmentService(db, college_id=int(cid) if cid is not None else None).handoff_tasks(actor.id), rid(request))


@router.post("/enrollment-handoff/tasks/{task_id}/review")
def review_task(
    task_id: int, body: TaskHandoffReview, actor: CurrentUserDep, db: Database, request: Request
):
    return success(
        EnrollmentService(db, college_id=int(request.path_params["cid"]) if "cid" in request.path_params else None).review_task(
            actor.id,
            task_id,
            body.lock_version,
            confirm_roster=body.confirm_roster,
            confirm_expected_count=body.confirm_expected_count,
            reason=body.reason,
            request_id=rid(request),
        ),
        rid(request),
    )


def rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.put("/teaching-classes/{teaching_class_id}/audiences")
def set_audience(
    teaching_class_id: int,
    body: AudienceRequest,
    actor: CurrentUserDep,
    db: Database,
    request: Request,
):
    return success(
        AudienceService(db).set(
            actor.id,
            teaching_class_id,
            body.administrative_class_ids,
            body.ownership_version,
            reason=body.reason,
            request_id=rid(request),
        ),
        rid(request),
    )


@router.get("/colleges")
def list_colleges(actor: CurrentUserDep, db: Database, request: Request):
    return success({"items": CollegeService(db).list(actor.id)}, rid(request))


@router.post("/colleges")
def create_college(
    body: CollegeCreateRequest, actor: CurrentUserDep, db: Database, request: Request
):
    return success(
        CollegeService(db).create(actor.id, body.code, body.name, request_id=rid(request)),
        rid(request),
    )


@router.get("/teacher-colleges/{user_id}")
def teacher_college(user_id: int, actor: CurrentUserDep, db: Database, request: Request):
    return success(CollegeService(db).teacher_college(actor.id, user_id), rid(request))


@router.put("/teacher-colleges/{user_id}")
def bind_teacher_college(
    user_id: int, body: TeacherCollegeRequest, actor: CurrentUserDep, db: Database, request: Request
):
    return success(
        CollegeService(db).set_teacher_college(
            actor.id, user_id, body.college_id, body.lock_version, request_id=rid(request)
        ),
        rid(request),
    )


@router.get("/student-manager-functions/{user_id}")
def manager_functions(user_id: int, actor: CurrentUserDep, db: Database, request: Request):
    return success(CollegeService(db).manager_functions(actor.id, user_id), rid(request))


@router.put("/student-manager-functions/{user_id}")
def set_manager_functions(
    user_id: int,
    body: ManagerFunctionsRequest,
    actor: CurrentUserDep,
    db: Database,
    request: Request,
):
    return success(
        CollegeService(db).set_manager_functions(
            actor.id, user_id, body.allowed_actions, body.lock_version, request_id=rid(request)
        ),
        rid(request),
    )


@router.post("/students/{student_id}/enrollment-changes/preview")
def preview_change(
    student_id: int,
    body: EnrollmentChangeRequest,
    actor: CurrentUserDep,
    db: Database,
    request: Request,
):
    return success(EnrollmentService(db).preview(actor.id, student_id, body), rid(request))


@router.post("/students/{student_id}/enrollment-changes")
def commit_change(
    student_id: int,
    body: EnrollmentChangeRequest,
    actor: CurrentUserDep,
    db: Database,
    request: Request,
):
    return success(
        EnrollmentService(db).commit(actor.id, student_id, body, request_id=rid(request)),
        rid(request),
    )


@router.get("/students/{student_id}/enrollment-history")
def history(student_id: int, actor: CurrentUserDep, db: Database, request: Request):
    return success(EnrollmentService(db).history(actor.id, student_id), rid(request))


@router.post("/students/{student_id}/enrollment-changes/{change_id}/cancel")
def cancel_change(
    student_id: int,
    change_id: int,
    body: VersionRequest,
    actor: CurrentUserDep,
    db: Database,
    request: Request,
):
    return success(
        EnrollmentService(db).cancel(
            actor.id,
            student_id,
            change_id,
            body.lock_version,
            reason=body.reason,
            request_id=rid(request),
        ),
        rid(request),
    )


@router.post("/student-data/preview")
def preview_data(
    body: StudentDataPreviewRequest, actor: CurrentUserDep, db: Database, request: Request
):
    return success(
        StudentDataService(db).preview(
            actor.id,
            college_id=body.college_id,
            rows=[r.model_dump(mode="json") for r in body.rows],
            purpose=body.purpose,
        ),
        rid(request),
    )


@router.post("/student-data/preview-file")
async def preview_file(
    actor: CurrentUserDep,
    db: Database,
    request: Request,
    college_id: Annotated[int, Form(ge=1)],
    file: Annotated[UploadFile, File()],
    purpose: Annotated[
        Literal["INCREMENTAL", "FULL_COMPARE", "ENROLLMENT_CHANGE"], Form()
    ] = "INCREMENTAL",
):
    content = await file.read(10 * 1024 * 1024 + 1)
    return success(
        StudentDataService(db).preview_file(actor.id, college_id, content, purpose=purpose),
        rid(request),
    )


@router.post("/student-data/{plan_id}/confirm")
def confirm_data(
    plan_id: int, body: VersionRequest, actor: CurrentUserDep, db: Database, request: Request
):
    return success(
        StudentDataService(db).confirm(
            actor.id, plan_id, body.lock_version, request_id=rid(request)
        ),
        rid(request),
    )


@router.get("/student-data/export")
def export_data(
    actor: CurrentUserDep,
    db: Database,
    college_id: Annotated[int, Query(ge=1)],
    include_archive: bool = False,
):
    return Response(
        content=StudentDataService(db).export(
            actor.id, college_id, include_archive=include_archive
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="student-handoff.xlsx"'},
    )
