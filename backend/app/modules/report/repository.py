"""统计/周报域仓储：仅只读聚合取数，绝不 commit、绝不写。

约定（技术方案 5.1、17）：
- 与 attendance/inspection 仓储同源，本波纯读，无写路径（周报生成写路径在 W7c 另建）；
- 一切"先范围过滤再聚合"的时间窗谓词经 `_task_window` 统一施加到子查询，命中集合只算一次，
  各聚合在其上做 GROUP BY，避免全表扫描（技术方案 17 第 544 行：仅统计符合条件任务）；
- 聚合以 SQL GROUP BY 完成，不在应用层拉取全量考勤逐行累加，杜绝大数据量下的内存放大。
"""

from __future__ import annotations

from datetime import date as date_
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.modules.attendance.models import AttendanceRecord, AttendanceType
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    TaskDeadlineAssessment,
    TaskRosterMember,
)


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---- 时间窗内"未取消"任务 id 子查询（命中集合的唯一真相源）----
    def _task_ids_subq(
        self,
        *,
        semester_id: int,
        week_no: int | None,
        date_from: date_ | None,
        date_to: date_ | None,
    ) -> Select:
        clauses: list[Any] = [
            InspectionTask.semester_id == semester_id,
            InspectionTask.canceled_at.is_(None),
        ]
        if week_no is not None:
            clauses.append(InspectionTask.week_no == week_no)
        else:
            assert date_from is not None and date_to is not None  # schemas 已校验二选一
            clauses.append(
                and_(
                    InspectionTask.inspection_date >= date_from,
                    InspectionTask.inspection_date <= date_to,
                )
            )
        return select(InspectionTask.id).where(*clauses)

    @staticmethod
    def _approved_submission_exists(aliased_task_id: Any) -> ColumnElement[bool]:
        """是否存在审核通过提交（EXISTS 子查询，用于筛"符合条件任务"）。"""
        return (
            select(InspectionSubmission.id)
            .where(
                InspectionSubmission.task_id == aliased_task_id,
                InspectionSubmission.review_status == ReviewStatus.APPROVED.value,
            )
            .exists()
        )

    def eligible_task_ids(
        self,
        *,
        semester_id: int,
        week_no: int | None,
        date_from: date_ | None,
        date_to: date_ | None,
    ) -> list[int]:
        """命中窗口内、未取消且存在审核通过提交的任务 id（技术方案 17：统计仅覆盖此类任务）。"""
        tid = self._task_ids_subq(
            semester_id=semester_id,
            week_no=week_no,
            date_from=date_from,
            date_to=date_to,
        ).subquery("win")
        stmt = select(tid.c.id).where(self._approved_submission_exists(tid.c.id))
        return sorted(int(r) for r in self._session.execute(stmt).scalars().all())

    def task_expected_counts(self, task_ids: list[int]) -> dict[int, tuple[int, int]]:
        """task_id -> (expected_count_current, expected_count_snapshot)；用于总量与调整标记。"""
        if not task_ids:
            return {}
        rows = self._session.execute(
            select(
                InspectionTask.id,
                InspectionTask.expected_count_current,
                InspectionTask.expected_count_snapshot,
            ).where(InspectionTask.id.in_(task_ids))
        ).all()
        return {int(tid): (int(cur), int(snap)) for tid, cur, snap in rows}

    def attendance_type_counts(self, task_ids: list[int]) -> dict[int, dict[str, int]]:
        """task_id -> {认定类型: 人数}（当前有效考勤，技术方案 12/14）。

        未列出的类型计数缺省为 0（服务侧用 `or 0` 归一）。仅统计审核通过任务（task_ids
        已由 eligible_task_ids 过滤），待审核异常自然不在其中（技术方案 17 第 544 行）。
        """
        if not task_ids:
            return {}
        rows = self._session.execute(
            select(
                AttendanceRecord.task_id,
                AttendanceRecord.effective_type,
                func.count(),
            )
            .where(AttendanceRecord.task_id.in_(task_ids))
            .group_by(AttendanceRecord.task_id, AttendanceRecord.effective_type)
        ).all()
        out: dict[int, dict[str, int]] = {}
        for tid, etype, cnt in rows:
            out.setdefault(int(tid), {})[str(etype)] = int(cnt)
        return out

    def task_meta(self, task_ids: list[int]) -> dict[int, dict[str, Any]]:
        """任务展示元数据：日期 / 周次 / 班级快照 / 课程快照。"""
        if not task_ids:
            return {}
        rows = self._session.execute(
            select(
                InspectionTask.id,
                InspectionTask.inspection_date,
                InspectionTask.week_no,
                InspectionTask.class_name_snapshot,
                InspectionTask.course_name_snapshot,
            ).where(InspectionTask.id.in_(task_ids))
        ).all()
        return {
            int(tid): {
                "inspection_date": idate,
                "week_no": int(wn),
                "class_name_snapshot": cname,
                "course_name_snapshot": course,
            }
            for tid, idate, wn, cname, course in rows
        }

    # ---- 班级维度（按名单快照分组，技术方案 17 第 554 行）----
    def roster_counts_by_task_class(
        self, task_ids: list[int], *, current_version_only: bool = True
    ) -> dict[tuple[int, str | None], int]:
        """(task_id, class_name_snapshot) -> 名单人数（去重学生）。

        按各任务当前 roster_version 过滤，与"据以生成考勤"的名单一致（技术方案 10）。
        class_name_snapshot 为空的成员归并到 key 的 None 段，由服务侧决定是否计入命名班级。
        """
        if not task_ids:
            return {}
        stmt = select(
            TaskRosterMember.task_id,
            TaskRosterMember.class_name_snapshot,
            func.count(func.distinct(TaskRosterMember.student_id)),
        ).where(TaskRosterMember.task_id.in_(task_ids))
        if current_version_only:
            # 仅保留成员名单版本 == 该任务当前 roster_version（经相关子查询）。
            rv = select(InspectionTask.roster_version).where(
                InspectionTask.id == TaskRosterMember.task_id
            )
            stmt = stmt.where(TaskRosterMember.roster_version == rv.scalar_subquery())
        stmt = stmt.group_by(TaskRosterMember.task_id, TaskRosterMember.class_name_snapshot)
        rows = self._session.execute(stmt).all()
        return {(int(tid), cname): int(cnt) for tid, cname, cnt in rows}

    def attendance_counts_by_task_class(
        self, task_ids: list[int]
    ) -> dict[tuple[int, str | None], dict[str, int]]:
        """(task_id, 名单班级快照) -> {认定类型: 人数}。

        考勤 join 当前版本名单成员取班级快照分组（异常者必在其任务当前名单内，技术方案 12），
        使班级异常分布与班级应到分布共用同一归并口径。
        """
        if not task_ids:
            return {}
        rv = select(InspectionTask.roster_version).where(
            InspectionTask.id == TaskRosterMember.task_id
        )
        type_cols = {
            etype.value: func.sum(
                case(
                    (
                        AttendanceRecord.effective_type == etype.value,
                        1,
                    ),
                    else_=0,
                )
            )
            for etype in AttendanceType
        }
        stmt = (
            select(
                AttendanceRecord.task_id,
                TaskRosterMember.class_name_snapshot,
                *(col.label(t) for t, col in type_cols.items()),
            )
            .join(
                TaskRosterMember,
                and_(
                    TaskRosterMember.task_id == AttendanceRecord.task_id,
                    TaskRosterMember.student_id == AttendanceRecord.student_id,
                    TaskRosterMember.roster_version == rv.scalar_subquery(),
                ),
            )
            .where(AttendanceRecord.task_id.in_(task_ids))
            .group_by(AttendanceRecord.task_id, TaskRosterMember.class_name_snapshot)
        )
        rows = self._session.execute(stmt).all()
        out: dict[tuple[int, str | None], dict[str, int]] = {}
        for tid, cname, normal, leave, late, absent in rows:
            out[(int(tid), cname)] = {
                "NORMAL": int(normal or 0),
                "LEAVE": int(leave or 0),
                "LATE": int(late or 0),
                "ABSENT": int(absent or 0),
            }
        return out

    # ---- 未完成清单（当前状态派生 + 截止时快照，技术方案 13.3/17）----
    def task_incomplete_flags(
        self,
        *,
        semester_id: int,
        week_no: int | None,
        date_from: date_ | None,
        date_to: date_ | None,
        page: int,
        page_size: int,
        only_current_incomplete: bool,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        """返回 (当前页任务行, total, current_incomplete_total, overdue_total)。

        - 命中窗口内未取消任务全纳入（含已取消截止快照？否：canceled 已被窗口排除）；
        - current_incomplete：无 APPROVED 提交（当前状态派生，技术方案 13 第 470 行）；
        - deadline_assessment/result：LEFT JOIN 截止快照，未到期为 None；
        - only_current_incomplete：True 时仅返回当前未完成者，total 也随之收敛，但
          current_incomplete_total / overdue_total 恒为窗口内全量口径（不随筛选变化）。
        """
        tid_subq = self._task_ids_subq(
            semester_id=semester_id, week_no=week_no, date_from=date_from, date_to=date_to
        )
        has_approved = self._approved_submission_exists(InspectionTask.id)
        has_pending = (
            select(InspectionSubmission.id)
            .where(
                InspectionSubmission.task_id == InspectionTask.id,
                InspectionSubmission.review_status == ReviewStatus.PENDING.value,
            )
            .exists()
        )

        base_cols = (
            InspectionTask.id,
            InspectionTask.inspection_date,
            InspectionTask.week_no,
            InspectionTask.class_name_snapshot,
            InspectionTask.course_name_snapshot,
            TaskDeadlineAssessment.result,
            TaskDeadlineAssessment.deadline_at_snapshot,
            TaskDeadlineAssessment.assignee_user_id_snapshot,
        )
        joined = (
            select(*base_cols, has_approved.label("has_approved"), has_pending.label("has_pending"))
            .outerjoin(
                TaskDeadlineAssessment,
                TaskDeadlineAssessment.task_id == InspectionTask.id,
            )
            .where(InspectionTask.id.in_(tid_subq))
        )
        # 全量口径两计数（不随 only_* 变化）
        cur_inc_where = and_(InspectionTask.id.in_(tid_subq), has_approved.is_(False))
        cur_incomplete_total = int(
            self._session.execute(
                select(func.count()).select_from(
                    select(InspectionTask.id)
                    .outerjoin(
                        TaskDeadlineAssessment,
                        TaskDeadlineAssessment.task_id == InspectionTask.id,
                    )
                    .where(cur_inc_where)
                    .subquery("ci")
                )
            ).scalar_one()
        )
        overdue_total = int(
            self._session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    TaskDeadlineAssessment.result == "OVERDUE_UNEXECUTED",
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    )
                )
                .select_from(InspectionTask)
                .outerjoin(
                    TaskDeadlineAssessment,
                    TaskDeadlineAssessment.task_id == InspectionTask.id,
                )
                .where(InspectionTask.id.in_(tid_subq))
            ).scalar_one()
        )

        if only_current_incomplete:
            joined = joined.where(has_approved.is_(False))

        # total：only_current_incomplete 时为当前未完成数，否则为窗口内未取消任务总数
        total = (
            cur_incomplete_total
            if only_current_incomplete
            else (
                int(
                    self._session.execute(
                        select(func.count()).select_from(
                            select(InspectionTask.id)
                            .outerjoin(
                                TaskDeadlineAssessment,
                                TaskDeadlineAssessment.task_id == InspectionTask.id,
                            )
                            .where(InspectionTask.id.in_(tid_subq))
                            .subquery("allt")
                        )
                    ).scalar_one()
                )
            )
        )

        rows = self._session.execute(
            joined.order_by(InspectionTask.inspection_date, InspectionTask.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()
        items = [
            {
                "task_id": int(r[0]),
                "inspection_date": r[1],
                "week_no": int(r[2]),
                "class_name_snapshot": r[3],
                "course_name_snapshot": r[4],
                "deadline_assessment": r[5],
                "deadline_at": r[6],
                "assignee_user_id": r[7],
                "current_incomplete": (not bool(r[8])),
                "has_pending": bool(r[9]),
            }
            for r in rows
        ]
        return items, total, cur_incomplete_total, overdue_total
