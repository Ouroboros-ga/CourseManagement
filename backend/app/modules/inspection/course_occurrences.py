"""精确课次选择：复用既有日历和名单规划，只补范围摘要与选择过滤。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import CourseOccurrenceScope, InspectionGenerateRequest

if TYPE_CHECKING:
    from app.modules.academic.models import Semester
    from app.modules.inspection.service import InspectionService, PlanItem


def build_scope(
    service: InspectionService,
    semester: Semester,
    scope: CourseOccurrenceScope,
) -> tuple[list[PlanItem], str]:
    """摘要覆盖整个查询范围，不含分页和任务受派状态，重复生成仍然幂等。"""
    body = InspectionGenerateRequest(
        semester_id=semester.id,
        inspection_type="COURSE",
        date_from=scope.date_from,
        date_to=scope.date_to,
        teaching_class_ids=sorted(set(scope.teaching_class_ids)),
        require_photo=scope.require_photo,
    )
    items = service._build_course_plan_core(semester, body)
    service._check_scale(len(items))
    items.sort(key=lambda i: (i.inspection_date, i.start_period, i.course_schedule_id or 0))
    periods = service._academic.list_period_definitions(semester.id)
    payload = {
        "semester": [
            semester.id,
            semester.start_date,
            semester.end_date,
            semester.first_monday,
            semester.total_weeks,
            semester.status,
        ],
        "scope": {
            **scope.model_dump(),
            "teaching_class_ids": sorted(set(scope.teaching_class_ids)),
        },
        "periods": sorted((p.period_no, str(p.start_time), str(p.end_time)) for p in periods),
        "items": [
            [
                i.task_key,
                i.week_no,
                i.course_name_snapshot,
                i.class_name_snapshot,
                i.classroom_snapshot,
                i.require_photo_snapshot,
                sorted(
                    (
                        m.student_id,
                        m.student_no,
                        m.name,
                        m.class_name_snapshot,
                        m.grade_year_snapshot,
                    )
                    for m in i.roster
                ),
            ]
            for i in items
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return items, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def select_occurrences(
    service: InspectionService,
    semester: Semester,
    body: InspectionGenerateRequest,
) -> list[PlanItem]:
    assert body.selection_scope is not None and body.occurrences is not None
    items, revision = build_scope(service, semester, body.selection_scope)
    if revision != body.selection_revision:
        raise ConflictError(ErrorCode.SELECTION_STALE, "课表、名单或生成条件已变化，请刷新预览")
    by_key = {(i.course_schedule_id, i.inspection_date): i for i in items}
    requested = {(x.course_schedule_id, x.inspection_date) for x in body.occurrences}
    if not requested <= by_key.keys():
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "包含范围外、停课或不可查的课次",
            http_status=422,
        )
    return [i for i in items if (i.course_schedule_id, i.inspection_date) in requested]


def list_occurrences(
    service: InspectionService,
    semester: Semester,
    scope: CourseOccurrenceScope,
    *,
    page: int,
    page_size: int,
) -> dict:
    items, revision = build_scope(service, semester, scope)
    selected = items[(page - 1) * page_size : page * page_size]
    tasks = (
        list(
            service._session.execute(
                select(InspectionTask).where(
                    InspectionTask.task_key.in_([i.task_key for i in selected])
                )
            ).scalars()
        )
        if selected
        else []
    )
    views = {t.task_key: t for t in service._assemble_tasks(tasks)}
    result = []
    for item in selected:
        existing = views.get(item.task_key)
        canceled = existing is not None and existing.status == "已取消"
        result.append(
            {
                "course_schedule_id": str(item.course_schedule_id),
                "inspection_date": item.inspection_date,
                "start_period": item.start_period,
                "end_period": item.end_period,
                "teaching_class_id": str(item.teaching_class_id),
                "class_name": item.class_name_snapshot,
                "course_name": item.course_name_snapshot,
                "classroom": item.classroom_snapshot,
                "existing_task_id": existing.id if existing else None,
                "existing_task_status": existing.status if existing else None,
                "selectable": not canceled,
                "disabled_reason": "已取消，请使用显式恢复" if canceled else None,
            }
        )
    return {
        "items": result,
        "page": page,
        "page_size": page_size,
        "total": len(items),
        "selection_revision": revision,
        "selection_scope": {
            **scope.model_dump(),
            "teaching_class_ids": [str(i) for i in scope.teaching_class_ids],
        },
    }
