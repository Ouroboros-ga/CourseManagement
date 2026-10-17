"""教职工任职关系的写入判定。

院级管理接口（`StaffManagementService`）与资料导入（`importer/staff_adapter`）走的是两种
编排：前者一次一个操作，后者整批 upsert/交接。两者必须使用同一套重叠口径，否则关系规则会
各自演化。本模块只做纯判定：查询与加锁由 `StaffRepository` 负责，写入与审计由调用方负责。

区间一律半开 `[effective_from, effective_to)`，`effective_to` 为空表示仍在任。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    TeachingStaffAssignment,
)


@dataclass(frozen=True)
class TeachingOverlap:
    """一名教师在重叠区间内的授课任命判定结果。

    `same_anchor` 是同锚点同资源的当前对照行（导入据此更新而不是新建）；
    `conflicts` 是不允许继续写入的行：同锚点的重复任命，以及另一锚点覆盖同一
    共享身份造成的职责来源歧义。
    """

    same_anchor: TeachingStaffAssignment | None
    conflicts: tuple[TeachingStaffAssignment, ...]

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def covered_offering_of(
    row: TeachingStaffAssignment, class_offering: str | None
) -> str | None:
    """任命实际触达的共享身份：SHARED 取自身，LOCAL 取教学班已确认的映射。

    关系行按锚点 CHECK 只能存其一，映射本身存在教学班上，所以 LOCAL 需要外部提供映射。
    """
    return row.academic_offering_id or class_offering


def classify_teaching_overlap(
    existing: Iterable[tuple[TeachingStaffAssignment, str | None]],
    *,
    anchor_type: str,
    teaching_class_id: int | None,
    academic_offering_id: str | None,
    covered_offering_id: str | None,
    exclude_id: int | None = None,
) -> TeachingOverlap:
    """把 `StaffRepository.overlapping_teaching` 的结果分成更新目标与冲突两类。

    `existing` 每项是 (重叠任命, 该任命本地教学班的共享身份)。跨锚点只在确实覆盖同一个
    共享身份时算冲突；未挂共享身份的本地班只按同锚点判定。
    """
    same_anchor: list[TeachingStaffAssignment] = []
    conflicts: list[TeachingStaffAssignment] = []
    for row, class_offering in existing:
        if exclude_id is not None and row.id == exclude_id:
            continue
        same_target = row.anchor_type == anchor_type and (
            row.teaching_class_id == teaching_class_id
            if anchor_type == "LOCAL"
            else row.academic_offering_id == academic_offering_id
        )
        if same_target:
            same_anchor.append(row)
        elif covered_offering_id and (
            covered_offering_of(row, class_offering) == covered_offering_id
        ):
            conflicts.append(row)
    if not same_anchor:
        return TeachingOverlap(same_anchor=None, conflicts=tuple(conflicts))
    # 同锚点重叠只允许一条：起始日最新的是在任任命，其余都是需要人工核对的重复。
    target = max(same_anchor, key=lambda row: (row.effective_from, row.id))
    conflicts.extend(row for row in same_anchor if row is not target)
    return TeachingOverlap(same_anchor=target, conflicts=tuple(conflicts))


def latest_responsibility(
    rows: Iterable[ClassStaffResponsibility],
) -> tuple[ClassStaffResponsibility | None, int]:
    """同班同职责的在任对照行；返回 (起始日最新的一条, 候选条数)。

    候选条数大于 1 说明数据已存在重叠任职，调用方必须停下而不是任选一条更新。
    """
    materialized = list(rows)
    if not materialized:
        return None, 0
    incumbent = max(
        materialized, key=lambda row: (row.effective_from, row.id)
    )
    return incumbent, len(materialized)


def handover_start_allowed(incumbent_from: date, effective_from: date) -> bool:
    """交接/补录的开始日必须晚于在任起始日，否则旧关系会被结束成空区间。"""
    return effective_from > incumbent_from


def interval_allowed(start: date, end: date | None) -> bool:
    """半开区间自身的合法性：结束日要么没有，要么晚于开始日。"""
    return end is None or end > start
