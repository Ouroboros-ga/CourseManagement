"""精确课次选择：复用既有日历和名单规划，只补范围摘要与选择过滤。"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import (
    CourseOccurrenceScope,
    InspectionGenerateRequest,
    SmartSampleRequest,
)

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
    requested = {(x.course_schedule_id, x.inspection_date) for x in body.occurrences}
    selected = []
    matched_req = set()
    for item in items:
        sched_ids = item.constituent_schedule_ids or ([item.course_schedule_id] if item.course_schedule_id else [])
        for sid in sched_ids:
            if (sid, item.inspection_date) in requested:
                selected.append(item)
                matched_req.add((sid, item.inspection_date))
                break
    if not requested <= matched_req:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "包含范围外、停课或不可查的课次",
            http_status=422,
        )
    return selected


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
                "teaching_class_name": item.class_name_snapshot,
                "course_name": item.course_name_snapshot,
                "classroom": item.classroom_snapshot,
                "classroom_name": item.classroom_snapshot,
                "expected_count": len(item.student_ids),
                "student_count": len(item.student_ids),
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


def smart_sample_occurrences(
    service: InspectionService,
    semester: Semester,
    body: SmartSampleRequest,
) -> dict[str, object]:
    """智能抽查推荐：根据早八优先、每班限额、排除已生成等规则推荐课次。"""
    from app.modules.academic.models import TeachingClass

    tcs = list(
        service._session.execute(
            select(TeachingClass).where(
                TeachingClass.semester_id == semester.id,
                TeachingClass.status == "ACTIVE",
            )
        ).scalars().all()
    )
    if not tcs:
        return {
            "semester_id": semester.id,
            "week_no": body.week_no,
            "total_candidates": 0,
            "sampled_count": 0,
            "occurrences": [],
            "items": [],
        }

    gen_req = InspectionGenerateRequest(
        semester_id=semester.id,
        inspection_type="COURSE",
        week_nos=[body.week_no],
        teaching_class_ids=[t.id for t in tcs],
    )
    all_plan_items = service._build_course_plan_core(semester, gen_req)

    if body.exclude_already_generated and all_plan_items:
        existing = service._repo.find_task_ids_by_keys([it.task_key for it in all_plan_items])
        candidates = [it for it in all_plan_items if it.task_key not in existing]
    else:
        candidates = list(all_plan_items)

    if body.morning_only:
        candidates = [it for it in candidates if it.start_period <= 2]

    if not candidates:
        return {
            "semester_id": semester.id,
            "week_no": body.week_no,
            "total_candidates": 0,
            "sampled_count": 0,
            "occurrences": [],
            "items": [],
        }

    # 随机发生器：若传入 random_seed 则便于单元测试复现，否则使用系统随机
    rng = random.Random(body.random_seed) if body.random_seed is not None else random.Random()

    by_class: dict[str, list[PlanItem]] = {}
    for it in candidates:
        c_name = it.class_name_snapshot or "默认"
        by_class.setdefault(c_name, []).append(it)

    class_keys = list(by_class.keys())
    rng.shuffle(class_keys)

    # 记录全周各日已被选中的查课任务数，用于平滑各工作日的查课负荷
    daily_tally: dict[object, int] = defaultdict(int)
    sampled: list[PlanItem] = []

    for c_name in class_keys:
        class_items = by_class[c_name]
        picked_for_class: list[PlanItem] = []
        picked_dates: set[object] = set()
        picked_keys: set[str] = set()

        k = min(body.max_tasks_per_class, len(class_items))
        for _ in range(k):
            available = [it for it in class_items if it.task_key not in picked_keys]
            if not available:
                break

            scored: list[tuple[float, PlanItem]] = []
            for it in available:
                # 优先级分层：0: 早八(<=2节), 1: 午前(3-4节), 2: 下午及晚间(>4节)
                if it.start_period <= 2:
                    tier = 0
                elif it.start_period <= 4:
                    tier = 1
                else:
                    tier = 2

                tier_penalty = tier * 1000.0
                # 同一行政班多节抽查时，优先分散到不同日期
                same_day_penalty = 100.0 if it.inspection_date in picked_dates else 0.0
                # 全周日期负载平滑：已有抽查任务较多的日期得分惩罚更高，彻底打破偏向周一的死板排序，促使周一至周五随机均匀抽查
                day_load_penalty = daily_tally[it.inspection_date] * 10.0
                # 随机扰动因子：打破确定性排序偏向，保证每次推荐均具随机探索性
                random_jitter = rng.uniform(0.0, 5.0)

                score = tier_penalty + same_day_penalty + day_load_penalty + random_jitter
                scored.append((score, it))

            scored.sort(key=lambda x: x[0])
            best_item = scored[0][1]
            picked_for_class.append(best_item)
            picked_keys.add(best_item.task_key)
            picked_dates.add(best_item.inspection_date)
            daily_tally[best_item.inspection_date] += 1

        sampled.extend(picked_for_class)

    # 抽查比例限制：随机抽样截取，杜绝按班级顺序截断的偏差
    if body.sample_ratio is not None and 0.0 < body.sample_ratio < 1.0:
        target_cnt = max(1, min(len(sampled), int(len(sampled) * body.sample_ratio)))
        sampled = rng.sample(sampled, target_cnt)

    # 最终结果按日期与节次升序排序，便于教务老师直观核对
    sampled.sort(key=lambda x: (x.inspection_date, x.start_period, x.class_name_snapshot or ""))

    out_occurrences = [
        {"course_schedule_id": it.course_schedule_id, "inspection_date": it.inspection_date}
        for it in sampled
        if it.course_schedule_id is not None
    ]
    out_items = [
        {
            "course_schedule_id": str(it.course_schedule_id),
            "inspection_date": it.inspection_date,
            "start_period": it.start_period,
            "end_period": it.end_period,
            "teaching_class_id": str(it.teaching_class_id),
            "class_name": it.class_name_snapshot,
            "teaching_class_name": it.class_name_snapshot,
            "course_name": it.course_name_snapshot,
            "classroom": it.classroom_snapshot,
            "classroom_name": it.classroom_snapshot,
            "expected_count": len(it.student_ids),
            "student_count": len(it.student_ids),
        }
        for it in sampled
        if it.course_schedule_id is not None
    ]

    return {
        "semester_id": semester.id,
        "week_no": body.week_no,
        "total_candidates": len(candidates),
        "sampled_count": len(sampled),
        "occurrences": out_occurrences,
        "items": out_items,
    }
