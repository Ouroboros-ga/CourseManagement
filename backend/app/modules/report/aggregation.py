"""考勤聚合口径纯函数（W7a/W7c 共用，技术方案 17）。

统计只读（W7a）与版本化周报生成（W7c）必须共用同一"先范围过滤再聚合"口径，杜绝两处
各写一套导致数字分叉。本模块把三件纯计算（全院汇总、班级归并、任务明细）从服务层抽出为
无守卫、无 IO 的函数：入参是 repository 已取好的分组字典，出参是 schema 对象。

调用方负责：
- 先经 eligible_task_ids 得到"审核通过且未取消"的命中集合（范围过滤，只算一次）；
- 再取 expected/att_by_task/roster_by_tc/att_by_tc/meta 五个分组结果传入。

口径要点（技术方案 17，与 service 层注释一致）：
1. 分母 = Σ expected_count_current，≤0 → statistics_available=false 且比率 null，不显示 0%/100%；
2. 先累加分子分母再相除，不对各班百分比简单平均；
3. 班级按 class_name_snapshot 归并；人工只调总数任务（cur≠snap）整任务从班级比例剔除，
   计 excluded_task_count、不均摊；
4. current_incomplete vs deadline_assessment 两指标互不混用（在 repository 未完成清单侧处理）。
"""

from __future__ import annotations

from typing import Any

from app.modules.attendance.models import AttendanceType
from app.modules.report.schemas import (
    ClassStatsItem,
    OverallStats,
    TaskStatsItem,
)

_TYPES = (
    AttendanceType.NORMAL,
    AttendanceType.LEAVE,
    AttendanceType.LATE,
    AttendanceType.ABSENT,
)


def sum_type_totals(att_by_task: dict[int, dict[str, int]]) -> dict[str, int]:
    """把各任务当前有效考勤按认定类型累加成全院合计。"""
    totals = {t.value: 0 for t in _TYPES}
    for counts in att_by_task.values():
        for t, c in counts.items():
            if t in totals:
                totals[t] += c
    return totals


def build_overall(exp_total: int, type_totals: dict[str, int], abnormal_total: int) -> OverallStats:
    available = exp_total > 0
    rate = (abnormal_total / exp_total) if available else None
    return OverallStats(
        statistics_available=available,
        expected_count=exp_total,
        abnormal_count=abnormal_total,
        normal_count=type_totals["NORMAL"],
        leave_count=type_totals["LEAVE"],
        late_count=type_totals["LATE"],
        absent_count=type_totals["ABSENT"],
        abnormal_rate=rate,
    )


def build_classes(
    expected: dict[int, tuple[int, int]],
    roster_by_tc: dict[tuple[int, str | None], int],
    att_by_tc: dict[tuple[int, str | None], dict[str, int]],
) -> list[ClassStatsItem]:
    """按班级名跨任务聚合。人工只调总数任务（cur≠snap）整任务从班级比例剔除。"""
    excluded_by_class: dict[str, int] = {}
    class_exp: dict[str, int] = {}
    class_cnt: dict[str, dict[str, int]] = {}

    def _is_excluded(tid: int) -> bool:
        cur, snap = expected.get(tid, (0, 0))
        return cur != snap

    keys = set(roster_by_tc) | set(att_by_tc)
    for tid, cname in keys:
        if not cname:  # 无班级快照者不参与"班级"维度（数据缺失，非可命名班）
            continue
        if _is_excluded(tid):
            excluded_by_class[cname] = excluded_by_class.get(cname, 0) + 1
            continue
        class_exp[cname] = class_exp.get(cname, 0) + roster_by_tc.get((tid, cname), 0)
        bucket = class_cnt.setdefault(cname, {t.value: 0 for t in _TYPES})
        for t, c in att_by_tc.get((tid, cname), {}).items():
            if t in bucket:
                bucket[t] += c

    names = set(class_exp) | set(excluded_by_class)
    items: list[ClassStatsItem] = []
    for cname in sorted(names):
        exp = class_exp.get(cname, 0)
        bucket = class_cnt.get(cname, {t.value: 0 for t in _TYPES})
        abnormal = bucket["LEAVE"] + bucket["LATE"] + bucket["ABSENT"]
        excluded = excluded_by_class.get(cname, 0)
        available = exp > 0
        items.append(
            ClassStatsItem(
                class_name=cname,
                expected_count=exp,
                abnormal_count=abnormal,
                normal_count=bucket["NORMAL"],
                leave_count=bucket["LEAVE"],
                late_count=bucket["LATE"],
                absent_count=bucket["ABSENT"],
                abnormal_rate=(abnormal / exp) if available else None,
                class_ratio_available=(excluded == 0 and available),
                excluded_task_count=excluded,
            )
        )
    return items


def build_tasks(
    ids: list[int],
    expected: dict[int, tuple[int, int]],
    att_by_task: dict[int, dict[str, int]],
    meta: dict[int, dict[str, Any]],
) -> list[TaskStatsItem]:
    out: list[TaskStatsItem] = []
    for tid in ids:
        cur, snap = expected.get(tid, (0, 0))
        counts = att_by_task.get(tid, {})
        abnormal = sum(
            counts.get(t.value, 0)
            for t in (AttendanceType.LEAVE, AttendanceType.LATE, AttendanceType.ABSENT)
        )
        m = meta.get(tid, {})
        out.append(
            TaskStatsItem(
                task_id=tid,
                inspection_date=m["inspection_date"],
                week_no=int(m.get("week_no", 0)),
                expected_count=cur,
                abnormal_count=abnormal,
                expected_count_adjusted=(cur != snap),
                class_ratio_available=(cur == snap),
            )
        )
    return out


__all__ = ["sum_type_totals", "build_overall", "build_classes", "build_tasks"]
