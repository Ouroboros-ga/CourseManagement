"""精确课次选择：复用既有日历和名单规划，只补范围摘要与选择过滤。"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.inspection.models import InspectionTask, TaskScheduleSource
from app.modules.inspection.schemas import (
    CourseOccurrenceScope,
    InspectionGenerateRequest,
    SmartSampleRequest,
)

if TYPE_CHECKING:
    from app.modules.academic.models import Semester
    from app.modules.inspection.service import InspectionService, PlanItem


def occurrence_location_terms(service, items) -> list[tuple[str, int]]:
    """课次地点修订摘要项：覆盖行修订号变化 → 选择摘要变化 → 旧生成预览 409。"""
    from app.modules.academic.occurrence_location import selection_summary_terms

    keys: set[str] = set()
    for item in items:
        keys.update(getattr(item, "occurrence_keys", []) or [])
    if not keys:
        return []
    return selection_summary_terms(service._session, keys)



def structural_duplicate_items(session, *, semester_id: int, items) -> list:
    """按真实课次结构找出与既有有效任务重复的计划项。

    `task_key` 是"学期+日期+类型+节次+目标标识"的派生字符串，历史上换过口径（共享课身份
    规范化、学院/课程类型后缀、非规范遗留值），同一堂真实课因此能建出第二个任务，各自排班、
    各自生成考勤，两道 key 守卫都拦不住（B3）。这里以课次的结构事实为准：目标课次来源
    （`task_schedule_source` / `course_schedule_id`）或自习的行政班，同学期、同日、同类型
    且节次区间相交即视为同一课次。不批量改写历史 `task_key`，也不自动清理既有任务；
    冲突原样返回给调用方显式处置。
    """
    from app.modules.inspection.service import PlanItem  # noqa: F401  仅类型说明

    def item_source_ids(item) -> set[int]:
        return set(
            item.constituent_schedule_ids
            or ([item.course_schedule_id] if item.course_schedule_id else [])
        )

    course_ids: set[int] = set()
    class_ids: set[int] = set()
    for item in items:
        course_ids |= item_source_ids(item)
        if item.administrative_class_id is not None:
            class_ids.add(item.administrative_class_id)
    if not (course_ids or class_ids):
        return []

    conds = []
    if course_ids:
        conds.append(InspectionTask.course_schedule_id.in_(course_ids))
        conds.append(
            select(TaskScheduleSource.task_id)
            .where(TaskScheduleSource.course_schedule_id.in_(course_ids))
            .correlate(InspectionTask)
            .exists()
        )
    if class_ids:
        conds.append(InspectionTask.administrative_class_id.in_(class_ids))
    existing = list(
        session.scalars(
            select(InspectionTask)
            .where(
                InspectionTask.semester_id == semester_id,
                InspectionTask.canceled_at.is_(None),
                InspectionTask.deleted_at.is_(None),
                or_(*conds),
            )
            .order_by(InspectionTask.id)
        )
    )
    if not existing:
        return []

    sources: dict[int, set[int]] = defaultdict(set)
    for task_id, schedule_id in session.execute(
        select(TaskScheduleSource.task_id, TaskScheduleSource.course_schedule_id).where(
            TaskScheduleSource.task_id.in_([task.id for task in existing])
        )
    ):
        sources[task_id].add(schedule_id)

    clashes = []
    for item in items:
        mine = item_source_ids(item)
        for task in existing:
            if task.task_key == item.task_key or task.inspection_date != item.inspection_date:
                continue
            if task.inspection_type != item.inspection_type:
                continue
            if not (task.start_period <= item.end_period and item.start_period <= task.end_period):
                continue
            theirs = sources[task.id]
            if task.course_schedule_id is not None:
                theirs.add(task.course_schedule_id)
            same_class = (
                item.administrative_class_id is not None
                and item.administrative_class_id == task.administrative_class_id
            )
            if (mine and theirs and mine & theirs) or (not mine and same_class):
                clashes.append((item, task))
                break
    return clashes


def build_scope(
    service: InspectionService,
    semester: Semester,
    scope: CourseOccurrenceScope,
) -> tuple[list[PlanItem], str]:
    """摘要覆盖整个查询范围，不含分页和任务受派状态，重复生成仍然幂等。"""
    from app.modules.academic.models import TeachingClass

    teaching_ids = scope.teaching_class_ids
    if scope.course_type_id is not None:
        teaching_ids = list(service._session.scalars(select(TeachingClass.id).where(
            TeachingClass.id.in_(teaching_ids), TeachingClass.course_type_id == int(scope.course_type_id))))
    items = []
    if teaching_ids:
        body = InspectionGenerateRequest(
            semester_id=semester.id,
            inspection_type="COURSE",
            date_from=scope.date_from,
            date_to=scope.date_to,
            teaching_class_ids=sorted(set(teaching_ids)),
            require_photo=scope.require_photo,
        )
        items = service._build_course_plan_core(semester, body)
    from app.modules.inspection.execution_group import validate
    items = validate(service, items, strict=False)
    service._check_scale(len(items))
    items.sort(key=lambda i: (i.inspection_date, i.start_period, i.course_schedule_id or 0))
    periods = service._academic.list_period_definitions(semester.id)
    payload = {
        "execution_group": ([service._generation_group[0].id, service._generation_group[0].lock_version,
                             service._generation_group[1].id] if service._generation_group else None),
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
        "occurrence_locations": occurrence_location_terms(service, items),
        "classifications": sorted((row.id, row.course_type_id, row.classification_revision)
            for row in service._session.scalars(select(TeachingClass).where(TeachingClass.id.in_(teaching_ids)))),
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
    from app.core.config import get_settings
    if get_settings().campus_scheduling_enabled:
        from app.modules.academic.models import TeachingClass
        from app.modules.academic.time_models import CollegeTimeVersion
        teaching = list(service._session.scalars(select(TeachingClass).where(TeachingClass.id.in_(scope.teaching_class_ids))))
        payload["time_bindings"] = sorted((row.id, row.time_profile_id, row.ownership_version) for row in teaching)
        payload["time_versions"] = sorted((row.id, row.version, row.profile_id) for row in service._session.scalars(
            select(CollegeTimeVersion).where(CollegeTimeVersion.semester_id == semester.id,
                CollegeTimeVersion.college_id.in_({row.college_id for row in teaching if row.college_id}))))
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
        canceled = existing is not None and (existing.status == "已取消" or existing.deleted_at is not None)
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
                "disabled_reason": "已取消或从日常管理删除，请使用显式恢复" if canceled else None,
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
    """智能抽查推荐：根据早八优先、每班限额、指定班级、排除已生成等规则推荐课次。"""
    from app.core.config import get_settings
    from app.core.exceptions import NotFoundError
    from app.modules.academic.models import (
        AdministrativeClass,
        Student,
        TeachingClass,
        TeachingClassStudent,
    )

    target_class_ids_set = set(body.target_class_ids) if body.target_class_ids else set()
    scoped = get_settings().campus_business_scoped_enabled
    colleges = service._repo.college_ids if scoped else None
    if scoped:
        requested = target_class_ids_set | {row.class_id for row in body.class_quotas or []}
        class_statement = select(AdministrativeClass).where(AdministrativeClass.id.in_(requested))
        if colleges is not None:
            class_statement = class_statement.where(AdministrativeClass.college_id.in_(colleges))
        confirmed = {row.id: row for row in service._session.scalars(class_statement)}
        if set(confirmed) != requested:
            raise NotFoundError("抽查班级或配额包含外院、未知归属或不存在的班级")
        target_ac_by_id = {cid: confirmed[cid].class_name for cid in target_class_ids_set}
        target_ac_names = set(target_ac_by_id.values())
        statement = select(TeachingClass).where(TeachingClass.semester_id == semester.id,
                                               TeachingClass.status == "ACTIVE")
        if colleges is not None:
            statement = statement.where(TeachingClass.college_id.in_(colleges))
        tcs = list(service._session.scalars(statement))

    # 1. 查询教学班
    elif target_class_ids_set:
        # 查询这些行政班的信息（获取班级名称）
        ac_rows = list(
            service._session.execute(
                select(AdministrativeClass).where(
                    AdministrativeClass.id.in_(list(target_class_ids_set))
                )
            ).scalars().all()
        )
        target_ac_by_id = {ac.id: ac.class_name for ac in ac_rows}
        target_ac_names = {ac.class_name for ac in ac_rows if ac.class_name}

        # 仅查询关联了目标班级学生的教学班
        tc_stmt = (
            select(TeachingClass)
            .where(
                TeachingClass.semester_id == semester.id,
                TeachingClass.status == "ACTIVE",
                select(TeachingClassStudent.student_id)
                .join(Student, Student.id == TeachingClassStudent.student_id)
                .where(
                    TeachingClassStudent.teaching_class_id == TeachingClass.id,
                    Student.administrative_class_id.in_(list(target_class_ids_set)),
                    Student.status == "ACTIVE",
                )
                .exists(),
            )
        )
        tcs = list(service._session.execute(tc_stmt).scalars().all())
    else:
        target_ac_by_id = {}
        target_ac_names = set()
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

    if body.course_type_id is not None:
        tcs = [row for row in tcs if row.course_type_id == int(body.course_type_id)]
    if not tcs:
        return {"semester_id": semester.id, "week_no": body.week_no, "total_candidates": 0,
                "sampled_count": 0, "occurrences": [], "items": []}
    gen_req = InspectionGenerateRequest(
        semester_id=semester.id,
        inspection_type="COURSE",
        week_nos=[body.week_no],
        teaching_class_ids=[t.id for t in tcs],
    )
    all_plan_items = service._build_course_plan_core(semester, gen_req)
    from app.modules.inspection.execution_group import validate
    all_plan_items = validate(service, all_plan_items, strict=False)

    # 若指定了目标班级，确保候选只包含属于目标班级的课次
    if target_class_ids_set:
        def _belongs_to_target_classes(it: PlanItem) -> bool:
            if scoped:
                return any(m.administrative_class_id_snapshot in target_class_ids_set for m in it.roster)
            for m in getattr(it, "roster", []):
                if m.class_name_snapshot and m.class_name_snapshot in target_ac_names:
                    return True
            if it.class_name_snapshot:
                for tname in target_ac_names:
                    if tname in it.class_name_snapshot:
                        return True
            return False

        all_plan_items = [it for it in all_plan_items if _belongs_to_target_classes(it)]

    if body.exclude_already_generated and all_plan_items:
        existing = service._repo.find_task_ids_by_keys([it.task_key for it in all_plan_items])
        candidates = [it for it in all_plan_items if it.task_key not in existing]
    else:
        candidates = list(all_plan_items)

    from app.modules.academic.time_service import TimeResolver
    resolver = TimeResolver(service._session) if get_settings().campus_scheduling_enabled else None
    starts = {}
    tc_colleges = {row.id: row.college_id for row in tcs}
    if resolver:
        for cid in {row.college_id for row in tcs if row.college_id is not None}:
            resolver.prefetch(cid, semester.id)

    def start_minute(item):
        if resolver is None:
            return None
        key = (item.teaching_class_id, item.inspection_date, item.start_period, item.end_period)
        if key not in starts:
            starts[key] = resolver.interval(tc_colleges[item.teaching_class_id], semester.id,
                item.inspection_date, item.start_period, item.end_period, teaching_class_id=item.teaching_class_id)["start_minute"]
        return starts[key]

    def tier(item):
        minute = start_minute(item)
        return (0 if minute < 9 * 60 else 1 if minute < 12 * 60 else 2) if minute is not None else (
            0 if item.start_period <= 2 else 1 if item.start_period <= 4 else 2)

    if body.morning_only:
        candidates = [it for it in candidates if (start_minute(it) < 12 * 60 if resolver else it.start_period <= 2)]

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

    # 构建各班配额映射字典
    quota_by_ac_id: dict[int, int] = {}
    quota_by_ac_name: dict[str, int] = {}
    if body.class_quotas:
        for cq in body.class_quotas:
            quota_by_ac_id[cq.class_id] = cq.max_tasks
            if cq.class_name:
                quota_by_ac_name[confirmed[cq.class_id].class_name if scoped else cq.class_name] = cq.max_tasks

    # 记录全周各日已被选中的查课任务数，用于平滑各工作日的查课负荷
    daily_tally: dict[object, int] = defaultdict(int)
    sampled: list[PlanItem] = []
    picked_keys: set[str] = set()
    picked_for_class: list[PlanItem]
    picked_dates: set[object]
    scored: list[tuple[float, PlanItem]]

    # 分组策略：
    # 场景 1：如果指定了目标班级（定向抽查模式），按每个目标班级分别进行抽查
    if target_class_ids_set:
        shuffled_targets = list(target_ac_by_id.items())
        rng.shuffle(shuffled_targets)

        for c_id, c_name in shuffled_targets:
            c_cap = quota_by_ac_id.get(
                c_id, quota_by_ac_name.get(c_name, body.max_tasks_per_class)
            )

            # 找出属于该班级的所有可用候选课次
            class_items = [
                it for it in candidates
                if (any(m.administrative_class_id_snapshot == c_id for m in it.roster) if scoped else
                    (c_name in {m.class_name_snapshot for m in getattr(it, "roster", []) if m.class_name_snapshot}))
                or (not scoped and it.class_name_snapshot and c_name in it.class_name_snapshot)
            ]

            picked_for_class = []
            picked_dates = set()

            for _ in range(c_cap):
                available = [it for it in class_items if it.task_key not in picked_keys]
                if not available:
                    break

                scored = []
                for it in available:
                    tier_penalty = tier(it) * 1000.0
                    same_day_penalty = 100.0 if it.inspection_date in picked_dates else 0.0
                    day_load_penalty = daily_tally[it.inspection_date] * 10.0
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

    else:
        # 场景 2：全校/全部班级均衡抽查（既有逻辑，兼容按 class_quotas 个性化配额）
        by_class: dict[str, list[PlanItem]] = {}
        for it in candidates:
            c_name = it.class_name_snapshot or "默认"
            by_class.setdefault(c_name, []).append(it)

        class_keys = list(by_class.keys())
        rng.shuffle(class_keys)

        for c_name in class_keys:
            class_items = by_class[c_name]
            picked_for_class = []
            picked_dates = set()

            class_cap = quota_by_ac_name.get(c_name, body.max_tasks_per_class)
            k = min(class_cap, len(class_items))
            for _ in range(k):
                available = [it for it in class_items if it.task_key not in picked_keys]
                if not available:
                    break

                scored = []
                for it in available:
                    tier_penalty = tier(it) * 1000.0
                    same_day_penalty = 100.0 if it.inspection_date in picked_dates else 0.0
                    day_load_penalty = daily_tally[it.inspection_date] * 10.0
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
        {"course_schedule_id": str(it.course_schedule_id), "inspection_date": it.inspection_date}
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
