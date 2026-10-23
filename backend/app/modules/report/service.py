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

from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import PermissionDeniedError, UnauthenticatedError
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.inspection.dimensions import TaskDimensions
from app.modules.report import aggregation as agg
from app.modules.report import permissions as perms
from app.modules.report.repository import ReportRepository
from app.modules.report.schemas import (
    AbnormalDetailItem,
    AttendanceStatsQuery,
    AttendanceStatsResponse,
    IncompleteTaskItem,
    IncompleteTasksResponse,
    TaskStatsItem,
)


class StatisticsService:
    def __init__(self, session: Session, *, college_id: int | None = None, dimensions: TaskDimensions | None = None) -> None:
        self._session = session
        self._college_id = college_id
        self.dimensions = dimensions
        self._repo = ReportRepository(session, dimensions=dimensions)
        self._identity = IdentityRepository(session)

    # ---- 守卫：功能权限纵深复核 + 管理范围准入 ----
    def _guard(self, actor: CurrentUser, code: str) -> None:
        from app.core.config import get_settings

        if get_settings().campus_business_scoped_enabled:
            colleges: frozenset[int] | None
            from app.modules.identity.management_scope import management_college_ids

            if self._college_id is not None:
                from app.modules.identity.resource_scope import resolve_scope
                resolve_scope(self._session, actor, self._college_id, code)
                colleges = frozenset({self._college_id})
            else:
                colleges = management_college_ids(self._session, actor, code)
            if colleges is not None and not colleges:
                raise PermissionDeniedError("没有此操作的学院管理范围")
            self._repo = ReportRepository(self._session, college_ids=colleges, dimensions=self.dimensions)
            return
        actor_row = self._identity.get_user_by_id(actor.id)
        if actor_row is None:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor.id)):
            raise PermissionDeniedError()
        if not perms.is_manage_scope(
            perms.resolve_read_scope(self._identity.list_effective_role_codes(actor.id))
        ):
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

        # ---- 全院：先累加分子分母，再相除（第 552 行）；口径与 W7c 共用 agg ----
        exp_total = sum(cur for cur, _snap in expected.values())
        type_totals = agg.sum_type_totals(att_by_task)
        abnormal_total = type_totals["LEAVE"] + type_totals["LATE"] + type_totals["ABSENT"]
        overall = agg.build_overall(exp_total, type_totals, abnormal_total)

        class_names = {cname for _tid, cname in (set(roster_by_tc) | set(att_by_tc)) if cname}
        dates = [m["inspection_date"] for m in meta.values()]
        class_duties = self._repo.class_duties_map(
            class_names, date_from=min(dates) if dates else None,
            date_to=max(dates) if dates else None,
        )
        classes = agg.build_classes(expected, roster_by_tc, att_by_tc, class_duties=class_duties)

        tasks: list[TaskStatsItem] | None = None
        details: list[AbnormalDetailItem] | None = None
        if include_tasks:
            tasks = agg.build_tasks(ids, expected, att_by_task, meta)
            raw_details = self._repo.abnormal_details(ids)
            details = [AbnormalDetailItem(**d) for d in raw_details]

        return AttendanceStatsResponse(
            semester_id=query.semester_id,
            week_no=query.week_no,
            date_from=query.date_from,
            date_to=query.date_to,
            exception_count=self._repo.exception_count(
                semester_id=query.semester_id, week_no=query.week_no,
                date_from=query.date_from, date_to=query.date_to,
            ),
            eligible_task_count=len(ids),
            overall=overall,
            classes=classes,
            tasks=tasks,
            details=details,
        )

    # ================================================================== #
    # GET /statistics/attendance/export
    # ================================================================== #
    def export_attendance_analytics(
        self,
        actor: CurrentUser,
        query: AttendanceStatsQuery,
    ) -> tuple[bytes, str]:
        stats_resp = self.attendance_stats(actor, query, include_tasks=True)
        meta = {
            "semester_id": query.semester_id,
            "week_no": query.week_no,
            "date_from": str(query.date_from) if query.date_from else None,
            "date_to": str(query.date_to) if query.date_to else None,
            "exception_count": stats_resp.exception_count,
            "eligible_task_count": stats_resp.eligible_task_count,
        }
        # attendance_stats 已按当前账号核验范围；标题只来自该范围，不信任客户端名称。
        if self._college_id is not None:
            from app.modules.organization.models import College

            college = self._session.get(College, self._college_id)
            meta["scope_name"] = college.name if college else "授权范围"
        else:
            meta["scope_name"] = "授权范围"
        task_ids = [int(t.task_id) for t in (stats_resp.tasks or []) if t.task_id]
        details = self._repo.abnormal_details(task_ids)
        payload = {
            "meta": meta,
            "overall": stats_resp.overall.model_dump(),
            "classes": [c.model_dump() for c in stats_resp.classes],
            "tasks": [t.model_dump() for t in (stats_resp.tasks or [])],
            "details": details,
        }
        from app.modules.report.artifacts import build_attendance_analytics_excel

        excel_bytes = build_attendance_analytics_excel(payload)
        if query.week_no:
            filename = f"attendance_analytics_w{query.week_no}.xlsx"
        else:
            filename = f"attendance_analytics_{query.date_from}_{query.date_to}.xlsx"
        return excel_bytes, filename

    # ================================================================== #
    # GET /statistics/attendance/export-detail-doc (独立 5 列详表 Word)
    # ================================================================== #
    def export_detail_word(
        self,
        actor: CurrentUser,
        query: AttendanceStatsQuery,
    ) -> tuple[bytes, str]:
        stats_resp = self.attendance_stats(actor, query, include_tasks=True)
        task_ids = [int(t.task_id) for t in (stats_resp.tasks or []) if t.task_id]
        details = self._repo.abnormal_details(task_ids)
        payload = {
            "meta": {
                "semester_id": query.semester_id,
                "week_no": query.week_no,
                "date_from": str(query.date_from) if query.date_from else None,
                "date_to": str(query.date_to) if query.date_to else None,
            },
            "overall": stats_resp.overall.model_dump(),
            "classes": [c.model_dump() for c in stats_resp.classes],
            "details": details,
        }
        from app.modules.report.artifacts import build_detail_table_word_document

        docx_bytes = build_detail_table_word_document(payload)
        week_tag = (
            f"第{query.week_no}周" if query.week_no else f"{query.date_from}至{query.date_to}"
        )
        filename = f"课堂考勤异常详表_{week_tag}.docx"
        return docx_bytes, filename

    # ================================================================== #
    # GET /statistics/attendance/export-study-excel (独立 4 列自习与日常考勤 Excel)
    # ================================================================== #
    def export_study_attendance_excel(
        self,
        actor: CurrentUser,
        query: AttendanceStatsQuery,
    ) -> tuple[bytes, str]:
        stats_resp = self.attendance_stats(actor, query, include_tasks=True)
        task_ids = [int(t.task_id) for t in (stats_resp.tasks or []) if t.task_id]
        details = self._repo.abnormal_details(task_ids)
        payload = {
            "meta": {
                "semester_id": query.semester_id,
                "week_no": query.week_no,
            },
            "details": details,
        }
        from app.modules.report.artifacts import build_study_attendance_excel

        excel_bytes = build_study_attendance_excel(payload)
        week_tag = (
            f"第{query.week_no}周" if query.week_no else f"{query.date_from}至{query.date_to}"
        )
        filename = f"自习与日常考勤表_{week_tag}.xlsx"
        return excel_bytes, filename

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
            exception_count=self._repo.exception_count(semester_id=semester_id, week_no=week_no,
                date_from=date_from, date_to=date_to),
            current_incomplete_count=cur_incomplete_total,
            overdue_unexecuted_count=overdue_total,
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=total,
        )


__all__ = ["StatisticsService"]
