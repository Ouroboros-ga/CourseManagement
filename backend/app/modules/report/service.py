"""统计域服务：跨任务的只读聚合口径（技术方案 17、PERMISSIONS.md 第 7 节）。

本波纯读、无事务写：不进 `_lock_actor`（无写者与之竞争行锁），仅做功能权限纵深复核
（重读有效权限，PERMISSIONS.md 13.2）与管理范围准入。范围与口径要点：

1. 仅统计「审核通过（存在 APPROVED 提交）且未取消」任务的当前有效考勤；待审核异常不计入
   正式缺勤（第 544 行）——命中集合由 repository 的 eligible_task_ids 一次算定；
2. 缺失率分母为有效应到（Σ task.expected_count_current），≤0 → 该维度
   statistics_available=false 且比率 null，不显示 0%/100%（第 552 行）；
3. 聚合先累加分子分母再相除，不对各班百分比简单平均（第 552 行）；
4. 班级维度按任务名单快照 class_name_snapshot 归并；若某任务当前应到≠初始快照（人工只调
   总数、无分班明细），该任务班级分母不可靠推导 → 其所有班级段 class_ratio_available=false
   并计入 excluded_task_count，不均摊、不臆造（第 554 行）；
5. 「当前未完成」与「截止时未完成」分别输出、不混名（第 470 行）：前者为当前无 APPROVED 提交
   的派生态，后者为 TaskDeadlineAssessment.result=OVERDUE_UNEXECUTED 的既成快照，未到期为 null。
"""

from __future__ import annotations

from datetime import date as date_
from typing import Any

from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
from app.modules.attendance.models import AttendanceType
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.report import permissions as perms
from app.modules.report.repository import ReportRepository
from app.modules.report.schemas import (
    AttendanceStatsQuery,
    AttendanceStatsResponse,
    ClassStatsItem,
    IncompleteTaskItem,
    IncompleteTasksResponse,
    OverallStats,
    TaskStatsItem,
)

_TYPES = (
    AttendanceType.NORMAL,
    AttendanceType.LEAVE,
    AttendanceType.LATE,
    AttendanceType.ABSENT,
)


class StatisticsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ReportRepository(session)
        self._identity = IdentityRepository(session)

    # ---- 守卫：功能权限纵深复核 + 管理范围准入 ----
    def _guard(self, actor: CurrentUser, code: str) -> None:
        actor_row = self._identity.get_user_by_id(actor.id)
        if actor_row is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor.id)):
            raise PermissionDeniedError()
        if not perms.is_manage_scope(perms.resolve_read_scope(actor.roles)):
            raise PermissionDeniedError("统计/周报为聚合读数，仅管理范围可见")

    # ================================================================== #
    # GET /statistics/attendance
    # ================================================================== #
    def attendance_stats(
        self,
        actor: CurrentUser,
        query: AttendanceStatsQuery,
        *,
        include_tasks: bool,
    ) -> AttendanceStatsResponse:
        self._guard(actor, perms.STATISTICS_READ_PERMISSION)
        ids = self._repo.eligible_task_ids(
            semester_id=query.semester_id,
            week_no=query.week_no,
            date_from=query.date_from,
            date_to=query.date_to,
        )
        expected = self._repo.task_expected_counts(ids)
        att_by_task = self._repo.attendance_type_counts(ids)
        roster_by_tc = self._repo.roster_counts_by_task_class(ids)
        att_by_tc = self._repo.attendance_counts_by_task_class(ids)
        meta = self._repo.task_meta(ids)

        # ---- 全院：先累加分子分母，再相除（第 552 行）----
        exp_total = sum(cur for cur, _snap in expected.values())
        type_totals = {t.value: 0 for t in _TYPES}
        for counts in att_by_task.values():
            for t, c in counts.items():
                if t in type_totals:
                    type_totals[t] += c
        abnormal_total = type_totals["LEAVE"] + type_totals["LATE"] + type_totals["ABSENT"]
        overall = self._build_overall(exp_total, type_totals, abnormal_total)

        classes = self._build_classes(ids, expected, roster_by_tc, att_by_tc)

        tasks: list[TaskStatsItem] | None = None
        if include_tasks:
            tasks = self._build_tasks(ids, expected, att_by_task, meta)

        return AttendanceStatsResponse(
            semester_id=query.semester_id,
            week_no=query.week_no,
            date_from=query.date_from,
            date_to=query.date_to,
            eligible_task_count=len(ids),
            overall=overall,
            classes=classes,
            tasks=tasks,
        )

    @staticmethod
    def _build_overall(
        exp_total: int, type_totals: dict[str, int], abnormal_total: int
    ) -> OverallStats:
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

    @staticmethod
    def _build_classes(
        ids: list[int],
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

    @staticmethod
    def _build_tasks(
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

    # ================================================================== #
    # GET /statistics/incomplete-tasks
    # ================================================================== #
    def incomplete_tasks(
        self,
        actor: CurrentUser,
        *,
        semester_id: int,
        week_no: int | None,
        date_from: date_ | None,
        date_to: date_ | None,
        params: PageParams,
        only_current_incomplete: bool,
    ) -> IncompleteTasksResponse:
        self._guard(actor, perms.STATISTICS_READ_PERMISSION)
        rows, total, cur_incomplete_total, overdue_total = self._repo.task_incomplete_flags(
            semester_id=semester_id,
            week_no=week_no,
            date_from=date_from,
            date_to=date_to,
            page=params.page,
            page_size=params.page_size,
            only_current_incomplete=only_current_incomplete,
        )
        items = [
            IncompleteTaskItem(
                task_id=r["task_id"],
                inspection_date=r["inspection_date"],
                week_no=r["week_no"],
                class_name_snapshot=r["class_name_snapshot"],
                course_name_snapshot=r["course_name_snapshot"],
                current_incomplete=r["current_incomplete"],
                deadline_assessment=r["deadline_assessment"],
                deadline_at=(
                    r["deadline_at"].isoformat() if r["deadline_at"] is not None else None
                ),
                assignee_user_id=r["assignee_user_id"],
            )
            for r in rows
        ]
        return IncompleteTasksResponse(
            semester_id=semester_id,
            week_no=week_no,
            date_from=date_from,
            date_to=date_to,
            current_incomplete_count=cur_incomplete_total,
            overdue_unexecuted_count=overdue_total,
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=total,
        )


__all__ = ["StatisticsService"]
