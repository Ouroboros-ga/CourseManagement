"""统计/周报域仓储：只读聚合取数 + 版本化周报读写助手，一律 flush-only、绝不 commit。

约定（技术方案 5.1、17、18）：
- ReportRepository 承接统计只读聚合：与 attendance/inspection 仓储同源，纯读、无写；
- 一切"先范围过滤再聚合"的时间窗谓词经 `_task_ids_subq` 统一施加到子查询，命中集合只算一次，
  各聚合在其上做 GROUP BY，避免全表扫描（技术方案 17 第 544 行：仅统计符合条件任务）；
- 聚合以 SQL GROUP BY 完成，不在应用层拉取全量考勤逐行累加，杜绝大数据量下的内存放大；
- W7c 新增 ReportVersionRepository：为版本化周报提供 get-or-create、版本登记、发布条件更新等
  写助手；与其余仓储一致——只 add/flush/条件 UPDATE，提交由上层 ReportService 在事务边界统一 commit。
"""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, and_, case, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.modules.attendance.models import AttendanceRecord, AttendanceType
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    TaskDeadlineAssessment,
    TaskRosterMember,
)
from app.modules.report.models import (
    Report,
    ReportSourceRevision,
    ReportVersion,
    ReportVersionStatus,
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

    # ---- 个人明细（供版本化周报快照，技术方案 18；下载受 report.read 约束）----
    def abnormal_details(self, task_ids: list[int]) -> list[dict[str, Any]]:
        """命中任务的非 NORMAL 当前有效考勤逐条明细（异常学生 + 班级快照）。

        join 当前 roster_version 名单成员取学号/姓名/班级快照；异常者必在其任务当前名单内
        （技术方案 12）。仅统计已过滤为符合条件（审核通过且未取消）的 task_ids。NORMAL 不入
        明细（周报正文只列异常个人，聚合人数走班级/任务维度）。
        """
        if not task_ids:
            return []
        rv = select(InspectionTask.roster_version).where(
            InspectionTask.id == TaskRosterMember.task_id
        )
        rows = self._session.execute(
            select(
                AttendanceRecord.task_id,
                AttendanceRecord.effective_type,
                TaskRosterMember.student_no,
                TaskRosterMember.name,
                TaskRosterMember.class_name_snapshot,
            )
            .join(
                TaskRosterMember,
                and_(
                    TaskRosterMember.task_id == AttendanceRecord.task_id,
                    TaskRosterMember.student_id == AttendanceRecord.student_id,
                    TaskRosterMember.roster_version == rv.scalar_subquery(),
                ),
            )
            .where(
                AttendanceRecord.task_id.in_(task_ids),
                AttendanceRecord.effective_type.in_(
                    [
                        AttendanceType.LEAVE.value,
                        AttendanceType.LATE.value,
                        AttendanceType.ABSENT.value,
                    ]
                ),
            )
            .order_by(AttendanceRecord.task_id, TaskRosterMember.student_no)
        ).all()
        return [
            {
                "task_id": int(r[0]),
                "attendance_type": str(r[1]),
                "student_no": r[2],
                "name": r[3],
                "class_name_snapshot": r[4],
            }
            for r in rows
        ]


class ReportVersionRepository:
    """版本化周报读写助手（W7c）：一律 flush-only、绝不 commit，提交归上层 ReportService。

    锁序遵循技术方案 512（考勤→异议→报表源修订→周报）：本仓储只在报表侧自身行上加锁，
    get-or-create 用 SELECT ... FOR UPDATE 串行化同 (学期,周,范围) 的版本号分配。
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_report(self, report_id: int) -> Report | None:
        return self._session.get(Report, report_id)

    def get_report_for_update(self, report_id: int) -> Report | None:
        return self._session.execute(
            select(Report).where(Report.id == report_id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def get_or_create_report_for_update(
        self, *, semester_id: int, week_no: int, scope: str
    ) -> Report:
        """原子建立唯一键对应的主记录，再取当前行锁，串行分配版本号。

        不先锁定查询空键：RR 下并发查空可各持间隙锁，随后 INSERT 升级形成死锁。
        MySQL 死锁会回滚整个事务，SAVEPOINT 无法只回滚失败的 INSERT。
        重复键只做 id 自赋值，不覆盖既有版本指针或更新时间。
        """
        statement = mysql_insert(Report).values(
            semester_id=semester_id, week_no=week_no, scope=scope, latest_version_no=0,
        )
        self._session.execute(statement.on_duplicate_key_update(id=Report.id))
        return self._session.execute(
            select(Report).where(Report.semester_id == semester_id,
                                 Report.week_no == week_no, Report.scope == scope)
            .with_for_update().execution_options(populate_existing=True)
        ).scalar_one()

    def latest_version(self, report_id: int) -> ReportVersion | None:
        # 鉴权可能已建立 RR 快照；必须看见等待主记录锁期间提交的 GENERATING。
        return self._session.execute(
            select(ReportVersion)
            .where(ReportVersion.report_id == report_id)
            .order_by(ReportVersion.version_no.desc())
            .limit(1).with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def list_versions(self, report_id: int) -> list[ReportVersion]:
        return list(
            self._session.execute(
                select(ReportVersion)
                .where(ReportVersion.report_id == report_id)
                .order_by(ReportVersion.version_no.desc())
            ).scalars()
        )

    def add_version(self, version: ReportVersion) -> None:
        self._session.add(version)
        self._session.flush()  # 取回 id 供发布阶段条件更新

    def get_version(self, version_id: int) -> ReportVersion | None:
        return self._session.get(ReportVersion, version_id)

    def get_version_for_update(self, version_id: int) -> ReportVersion | None:
        return self._session.execute(
            select(ReportVersion)
            .where(ReportVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def current_source_revision(self, semester_id: int, week_no: int) -> int:
        """当前 (学期,周) 考勤源修订号（无行即 0），供生成时读取与落后判定。"""
        val = self._session.execute(
            select(ReportSourceRevision.revision).where(
                ReportSourceRevision.semester_id == semester_id,
                ReportSourceRevision.week_no == week_no,
            )
        ).scalar_one_or_none()
        return 0 if val is None else int(val)

    def take_over_stale_generating(
        self,
        *,
        version_id: int,
        old_token: str,
        new_token: str,
        stale_before: datetime,
    ) -> int:
        """接管停留在 GENERATING 且已超预算（created_at 早于 stale_before）的版本行。

        条件更新原子换令牌：仅当该行仍为 GENERATING、attempt_token 仍等于 old_token 时改写为
        new_token。返回受影响行数（0 表示已被他人接管/发布，调用方据此放弃接管）。
        """
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(ReportVersion)
                .where(
                    ReportVersion.id == version_id,
                    ReportVersion.status == ReportVersionStatus.GENERATING.value,
                    ReportVersion.attempt_token == old_token,
                    ReportVersion.created_at < stale_before,
                )
                .values(attempt_token=new_token)
            ),
        )
        self._session.flush()
        return int(result.rowcount or 0)
