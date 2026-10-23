"""Explicit summary-only school access and resource-bounded group performance."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.common.responses import success
from app.core.database import get_db
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.attendance.models import AttendanceRecord
from app.modules.attendance.scoped_router import require_business_scoped_enabled
from app.modules.identity.deps import CurrentUserDep
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.dimensions import DimensionsDep
from app.modules.inspection.models import InspectionAssignment, InspectionSubmission, InspectionTask
from app.modules.organization.models import College
from app.modules.organization.router import require_campus_enabled
from app.modules.organization.service import CampusService
from app.modules.volunteer.models import VolunteerGroup

router = APIRouter(
    tags=["summary-statistics"],
    dependencies=[Depends(require_campus_enabled), Depends(require_business_scoped_enabled)],
)
Db = Annotated[Session, Depends(get_db)]
ResourceId = Annotated[int, Path(gt=0, le=2**63 - 1)]
SemesterId = Annotated[int, Query(gt=0, le=2**63 - 1)]


def totals(rows):
    return {key: sum(row[key] for row in rows) for key in (
        "task_count", "assigned_count", "submitted_count", "completed_count",
        "incomplete_count", "exception_count")}


def aggregate(db, semester_id, conditions, *, attendance=False):
    if db.get(Semester, semester_id) is None:
        raise NotFoundError("学期不存在")
    submitted = (
        select(InspectionSubmission.id)
        .where(InspectionSubmission.task_id == InspectionTask.id)
        .exists()
    )
    completed = (
        select(InspectionSubmission.id)
        .where(
            InspectionSubmission.task_id == InspectionTask.id,
            InspectionSubmission.review_status == "APPROVED",
        )
        .exists()
    )
    assigned = (
        select(InspectionAssignment.id)
        .where(
            InspectionAssignment.task_id == InspectionTask.id,
            InspectionAssignment.revoked_at.is_(None),
        )
        .exists()
    )
    dimensions = [
        InspectionTask.college_id,
        InspectionTask.course_type_id_snapshot,
        InspectionTask.course_type_name_snapshot,
        InspectionTask.group_id,
        InspectionTask.group_name_snapshot,
    ]
    effective = InspectionTask.exception_reported_at.is_(None)
    statement = (
        select(
            *dimensions,
            func.sum(case((effective, 1), else_=0)).label("task_count"),
            func.sum(case((~effective, 1), else_=0)).label("exception_count"),
            func.sum(case((effective & assigned, 1), else_=0)).label("assigned_count"),
            func.sum(case((submitted, 1), else_=0)).label("submitted_count"),
            func.sum(case((completed, 1), else_=0)).label("completed_count"),
            func.sum(case((completed, InspectionTask.expected_count_current), else_=0)).label(
                "expected_count"
            ),
        )
        .where(
            InspectionTask.semester_id == semester_id,
            InspectionTask.canceled_at.is_(None),
            *conditions,
        )
        .group_by(*dimensions)
    )
    # Separate aggregation avoids multiplying task denominators by roster rows.
    counts = {}
    if attendance:
        att = select(*dimensions, AttendanceRecord.effective_type, func.count())
        att = (
            att.join(AttendanceRecord, AttendanceRecord.task_id == InspectionTask.id)
            .where(
                InspectionTask.semester_id == semester_id,
                InspectionTask.canceled_at.is_(None),
                completed,
                *conditions,
            )
            .group_by(*dimensions, AttendanceRecord.effective_type)
        )
        for *key, kind, count in db.execute(att):
            counts.setdefault(tuple(key), {})[kind] = count
    result = []
    for *key, total, exceptional, allocated, sent, done, expected in db.execute(statement):
        item = dict(
            zip(
                ["college_id", "course_type_id", "course_type_name", "group_id", "group_name"],
                key,
                strict=True,
            )
        )
        for name in ("college_id", "course_type_id", "group_id"):
            item[name] = str(item[name]) if item[name] is not None else None
        item.update(
            task_count=int(total or 0),
            exception_count=int(exceptional or 0),
            assigned_count=int(allocated or 0),
            submitted_count=int(sent or 0),
            completed_count=int(done or 0),
            incomplete_count=int(total or 0) - int(done or 0),
        )
        if attendance:
            item.update(
                expected_count=int(expected or 0), attendance_counts=counts.get(tuple(key), {})
            )
        result.append(item)
    return sorted(
        result,
        key=lambda row: tuple(
            str(row[k] or "")
            for k in ("college_id", "course_type_id", "group_id", "course_type_name", "group_name")
        ),
    )


@router.get("/statistics/school-summary")
def school_summary(
    actor: CurrentUserDep, db: Db, semester_id: SemesterId, dimensions: DimensionsDep
):
    campus = CampusService(db)
    campus._actor(actor)
    identity = IdentityRepository(db)
    roles = set(identity.list_role_codes(actor.id))
    if not roles & {"SUPER_ADMIN", "TEACHER_ADMIN"} or (
        "statistics.school.read" not in identity.list_effective_permissions(actor.id)
    ):
        raise PermissionDeniedError("需要独立的全校汇总查看权限")
    rows = aggregate(db, semester_id, dimensions.conditions(), attendance=True)
    names = {str(row.id): row.name for row in db.scalars(select(College))}
    return success(
        {
            "semester_id": str(semester_id),
            "items": [
                {**row, "college_name": names.get(row["college_id"], "待确认学院归属")}
                for row in rows
            ],
            "summary_only": True,
            "totals": totals(rows),
        }
    )


@router.get("/colleges/{cid}/groups/{gid}/statistics/performance")
def group_performance(
    cid: ResourceId, gid: ResourceId, actor: CurrentUserDep, db: Db, semester_id: SemesterId
):
    # Group-read alone does not confer school/student statistics or personal details.
    scope = resolve_scope(db, actor, cid, "volunteer.group.read")
    if not scope.permits_group(gid):
        raise NotFoundError()
    CampusService(db)._resource(VolunteerGroup, cid, gid)
    rows = aggregate(
        db,
        semester_id,
        [InspectionTask.college_id == cid, InspectionTask.group_id == gid, scope.task_condition()],
    )
    return success({"semester_id": str(semester_id), "group_id": str(gid),
                    "items": rows, "totals": totals(rows)})
