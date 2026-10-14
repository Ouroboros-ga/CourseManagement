"""学院路径中的正式基础数据入口；范围鉴权在 Service 内逐操作执行。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, page_params
from app.common.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ErrorCode
from app.modules.academic.scoped_service import (
    ScopedAcademicService,
    ScopedClassCreate,
    ScopedClassUpdate,
)
from app.modules.identity.deps import CurrentUserDep
from app.modules.organization.router import require_campus_enabled
from app.modules.organization.schemas import StrictModel

ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
ResourceKind = Literal[
    "administrative-classes",
    "teaching-classes",
    "students",
    "schedules",
    "courses",
    "semesters",
    "qualifications",
]
StudentId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class ScopedRosterReplace(StrictModel):
    student_ids: list[StudentId] = Field(max_length=5000)
    ownership_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=512)


class ScopedClassification(StrictModel):
    course_type_id: StudentId
    classification_revision: int = Field(ge=1)
    future_impact_revision: str = Field(default="", max_length=64, pattern=r"^(?:|[0-9a-f]{64})$")

    @field_validator("course_type_id")
    @classmethod
    def valid_type_id(cls, value):
        if int(value) >= 2**63:
            raise ValueError("课程类型标识超出 BIGINT 范围")
        return value


def require_scoped_academic_enabled():
    if not get_settings().campus_academic_scoped_enabled:
        raise AppError(ErrorCode.STATE_CONFLICT, "院级基础数据接入尚未启用", 503)


router = APIRouter(
    tags=["college-academic"],
    dependencies=[Depends(require_campus_enabled), Depends(require_scoped_academic_enabled)],
)


def get_service(
    cid: ResourceId,
    actor: CurrentUserDep,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    return ScopedAcademicService(db, actor, cid, getattr(request.state, "request_id", None))


ServiceDep = Annotated[ScopedAcademicService, Depends(get_service)]


@router.put("/colleges/{cid}/academic/teaching-classes/{rid}/course-type")
def classify(
    cid: ResourceId,
    rid: ResourceId,
    body: ScopedClassification,
    service: ServiceDep,
    request: Request,
):
    result = service.set_course_type(rid, int(body.course_type_id), body.classification_revision,
                                     body.future_impact_revision)
    return success(result, getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/academic/teaching-classes/{rid}/classification-impact")
def classification_impact(cid: ResourceId, rid: ResourceId, service: ServiceDep, request: Request):
    return success(service.classification_impact(rid), getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/academic/master-timetable")
def master_timetable(cid: ResourceId, service: ServiceDep, request: Request,
                     semester_id: Annotated[int, Query(gt=0, le=2**63 - 1)],
                     week_no: Annotated[int | None, Query(ge=1, le=60)] = None,
                     weekday: Annotated[int | None, Query(ge=1, le=7)] = None,
                     administrative_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
                     keyword: Annotated[str | None, Query(max_length=128)] = None):
    from app.modules.academic.scoped_timetable import master_timetable as query
    return success(query(service, semester_id, week_no=week_no, weekday=weekday,
                         administrative_class_id=administrative_class_id, keyword=keyword),
                   getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/academic/{kind}")
def list_rows(
    cid: ResourceId,
    kind: ResourceKind,
    service: ServiceDep,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    semester_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
    administrative_class_id: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None,
):
    result = service.list_rows(
        kind.replace("-", "_"),
        params,
        keyword=keyword,
        semester_id=semester_id,
        administrative_class_id=administrative_class_id,
    )
    return success(result, getattr(request.state, "request_id", None))


@router.get("/colleges/{cid}/academic/{kind}/{rid}")
def get_row(
    cid: ResourceId, kind: ResourceKind, rid: ResourceId, service: ServiceDep, request: Request
):
    return success(
        service.get_row(kind.replace("-", "_"), rid), getattr(request.state, "request_id", None)
    )


@router.post("/colleges/{cid}/academic/administrative-classes")
def create_class(cid: ResourceId, body: ScopedClassCreate, service: ServiceDep, request: Request):
    return success(
        service.create_admin_class(body.model_dump()), getattr(request.state, "request_id", None)
    )


@router.patch("/colleges/{cid}/academic/administrative-classes/{rid}")
def update_class(
    cid: ResourceId, rid: ResourceId, body: ScopedClassUpdate, service: ServiceDep, request: Request
):
    return success(
        service.update_admin_class(rid, body.model_dump(exclude_unset=True)),
        getattr(request.state, "request_id", None),
    )


@router.get("/colleges/{cid}/academic/teaching-classes/{rid}/roster")
def get_roster(cid: ResourceId, rid: ResourceId, service: ServiceDep, request: Request):
    return success(service.list_roster(rid), getattr(request.state, "request_id", None))


@router.put("/colleges/{cid}/academic/teaching-classes/{rid}/roster")
def replace_roster(
    cid: ResourceId,
    rid: ResourceId,
    body: ScopedRosterReplace,
    service: ServiceDep,
    request: Request,
):
    return success(
        service.replace_roster(rid, body.student_ids, body.ownership_version, body.reason),
        getattr(request.state, "request_id", None),
    )
