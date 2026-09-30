"""查课任务与排班仓储：仅取数 / 加锁读 / 增删改并 flush，绝不自行 commit。

约定与 academic / identity 仓储一致（技术方案 5.1、15、PERMISSIONS.md 13.2）：
- 提交由 Service 统一在事务末尾单次完成；
- 需要行级串写的读用 `*_for_update`（SELECT ... FOR UPDATE + populate_existing）；
- 列表查询返回 (items, total)，分页由 Service 传入 PageParams；列表状态/计数一律用集合
  查询或聚合，禁止对每条任务逐次查询（技术方案 12）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as date_
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, case, func, select, tuple_
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    SubmissionDeadlineDay,
    SubmissionDeadlineVersion,
    SubmissionFile,
    TaskDeadlineAssessment,
    TaskRosterMember,
    TaskRosterVersion,
    VolunteerDayLock,
)


def _paged(session: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    count_sub = stmt.order_by(None).subquery()
    total = session.execute(select(func.count()).select_from(count_sub)).scalar_one()
    items = list(
        session.execute(stmt.limit(params.limit).offset(params.offset)).scalars().unique().all()
    )
    return items, int(total)


def _for_update(stmt: Select):  # noqa: ANN202 - 返回 Executable 由调用方 execute
    return stmt.with_for_update().execution_options(populate_existing=True)


class InspectionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ==================== 通用 ====================
    def add(self, obj: object) -> None:
        self._session.add(obj)

    def flush(self) -> None:
        self._session.flush()

    # ==================== 任务 ====================
    def get_task(self, task_id: int) -> InspectionTask | None:
        return self._session.get(InspectionTask, task_id)

    def list_tasks_by_ids(self, task_ids: Sequence[int]) -> list[InspectionTask]:
        if not task_ids:
            return []
        return list(
            self._session.execute(
                select(InspectionTask).where(InspectionTask.id.in_(set(task_ids)))
            ).scalars().all()
        )

    def get_task_for_update(self, task_id: int) -> InspectionTask | None:
        stmt = _for_update(select(InspectionTask).where(InspectionTask.id == task_id))
        return self._session.execute(stmt).scalar_one_or_none()

    def get_task_by_key(self, task_key: str) -> InspectionTask | None:
        return self._session.execute(
            select(InspectionTask).where(InspectionTask.task_key == task_key)
        ).scalar_one_or_none()

    def find_task_ids_by_keys(self, keys: Sequence[str]) -> set[str]:
        if not keys:
            return set()
        rows = self._session.execute(
            select(InspectionTask.task_key).where(InspectionTask.task_key.in_(keys))
        ).all()
        return {row[0] for row in rows}

    def get_task_scoped(
        self, task_id: int, *, scope_filter: Select | None = None
    ) -> InspectionTask | None:
        """在给定可见性谓词内按 id 取单条任务；不可见或不存在均返回 None。

        scope_filter 为 service 依数据范围构造的 `select(InspectionTask) [WHERE ...]`，
        与列表查询共用同一谓词（PERMISSIONS.md 7）；None 表示管理范围（全部可见）。
        """
        stmt = scope_filter if scope_filter is not None else select(InspectionTask)
        stmt = stmt.where(InspectionTask.id == task_id)
        return self._session.execute(stmt).scalars().unique().one_or_none()

    def list_tasks(
        self,
        params: PageParams,
        *,
        scope_filter: Select | None = None,
        semester_id: int | None = None,
        inspection_date: date_ | None = None,
        week_no: int | None = None,
        inspection_type: str | None = None,
        teaching_class_id: int | None = None,
        administrative_class_id: int | None = None,
        include_canceled: bool = True,
    ) -> tuple[list[InspectionTask], int]:
        """按数据范围谓词 + 可选业务过滤列出任务。

        scope_filter 是由 Service 依数据范围（SYSTEM_WIDE / ALL_GRADES / ASSIGNED_TASK）
        构造并传入的、已 select(InspectionTask) 并施加可见性条件的语句；仓储仅再叠加过滤，
        保证列表 / 详情 / 计数共用同一可见性谓词（技术方案 / PERMISSIONS.md 7）。
        """
        stmt = scope_filter if scope_filter is not None else select(InspectionTask)
        if semester_id is not None:
            stmt = stmt.where(InspectionTask.semester_id == semester_id)
        if inspection_date is not None:
            stmt = stmt.where(InspectionTask.inspection_date == inspection_date)
        if week_no is not None:
            stmt = stmt.where(InspectionTask.week_no == week_no)
        if inspection_type is not None:
            stmt = stmt.where(InspectionTask.inspection_type == inspection_type)
        if teaching_class_id is not None:
            stmt = stmt.where(InspectionTask.teaching_class_id == teaching_class_id)
        if administrative_class_id is not None:
            stmt = stmt.where(InspectionTask.administrative_class_id == administrative_class_id)
        if not include_canceled:
            stmt = stmt.where(InspectionTask.canceled_at.is_(None))
        stmt = stmt.order_by(InspectionTask.inspection_date, InspectionTask.id)
        return _paged(self._session, stmt, params)

    # ==================== 名单版本 / 成员 ====================
    def get_roster_version(self, task_id: int, version_no: int) -> TaskRosterVersion | None:
        return self._session.execute(
            select(TaskRosterVersion).where(
                TaskRosterVersion.task_id == task_id,
                TaskRosterVersion.version_no == version_no,
            )
        ).scalar_one_or_none()

    def list_roster_versions(self, task_id: int) -> list[TaskRosterVersion]:
        return list(
            self._session.execute(
                select(TaskRosterVersion)
                .where(TaskRosterVersion.task_id == task_id)
                .order_by(TaskRosterVersion.version_no)
            )
            .scalars()
            .all()
        )

    def list_roster_members(
        self, task_id: int, roster_version: int
    ) -> list[TaskRosterMember]:
        return list(
            self._session.execute(
                select(TaskRosterMember)
                .where(
                    TaskRosterMember.task_id == task_id,
                    TaskRosterMember.roster_version == roster_version,
                )
                .order_by(TaskRosterMember.student_id)
            )
            .scalars()
            .all()
        )

    def count_roster_members(self, task_id: int, roster_version: int) -> int:
        return int(
            self._session.execute(
                select(func.count())
                .select_from(TaskRosterMember)
                .where(
                    TaskRosterMember.task_id == task_id,
                    TaskRosterMember.roster_version == roster_version,
                )
            ).scalar_one()
        )

    def list_roster_members_by_task_ids(
        self, task_ids: Sequence[int]
    ) -> dict[int, list[TaskRosterMember]]:
        """批量取每个任务**当前（最大）名单版本**的成员，避免列表/详情逐任务查询。

        以相关子查询过滤到每任务的最大 version：仅取该任务最新名单快照成员。
        """
        ids = list(task_ids)
        if not ids:
            return {}
        max_ver = (
            select(func.max(TaskRosterMember.roster_version))
            .where(TaskRosterMember.task_id == InspectionTask.id)
            .correlate(InspectionTask)
            .scalar_subquery()
        )
        rows = self._session.execute(
            select(TaskRosterMember)
            .where(
                TaskRosterMember.task_id.in_(ids),
                TaskRosterMember.roster_version
                == max_ver,
            )
            .order_by(TaskRosterMember.task_id, TaskRosterMember.student_id)
        ).scalars().all()
        grouped: dict[int, list[TaskRosterMember]] = {}
        for m in rows:
            grouped.setdefault(m.task_id, []).append(m)
        return grouped

    # ==================== 受派关系 ====================
    def get_assignment_by_task(self, task_id: int) -> InspectionAssignment | None:
        return self._session.execute(
            select(InspectionAssignment).where(
                InspectionAssignment.task_id == task_id,
                InspectionAssignment.revoked_at.is_(None),
            )
        ).scalar_one_or_none()

    def get_assignment_by_task_for_update(self, task_id: int) -> InspectionAssignment | None:
        stmt = _for_update(
            select(InspectionAssignment).where(
                InspectionAssignment.task_id == task_id,
                InspectionAssignment.revoked_at.is_(None),
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_assignment(self, assignment_id: int) -> InspectionAssignment | None:
        return self._session.get(InspectionAssignment, assignment_id)

    def get_assignment_for_update(self, assignment_id: int) -> InspectionAssignment | None:
        stmt = _for_update(
            select(InspectionAssignment).where(InspectionAssignment.id == assignment_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_assignments_by_task_ids(
        self, task_ids: Sequence[int]
    ) -> dict[int, InspectionAssignment]:
        """批量取每个任务当前受派，历史失效行不占用当前受派视图。"""
        ids = list(task_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(InspectionAssignment).where(
                InspectionAssignment.task_id.in_(ids),
                InspectionAssignment.revoked_at.is_(None),
            )
        ).scalars().all()
        return {a.task_id: a for a in rows}

    def list_assignments_for_volunteer_on_date(
        self, volunteer_user_id: int, on_date: date_, *, for_update: bool = False
    ) -> list[tuple[InspectionAssignment, InspectionTask]]:
        """取某志愿者某日已受派的任务（含任务时间区间），用于排班冲突重查。

        for_update=True 用 SELECT ... FOR SHARE（读意向共享锁）读取最新已提交行：
        在已持有 (志愿者, 日期) 锚点排他锁的临界区内，普通快照读会错过并发方刚提交的
        受派（REPEATABLE READ 读视图在本事务首次一致性读时定版），锁定读则绕过旧读视图，
        确保重叠时段冲突判定看到真实最新状态（技术方案 15）。
        """
        stmt = (
            select(InspectionAssignment, InspectionTask)
            .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
            .where(
                InspectionAssignment.volunteer_user_id == volunteer_user_id,
                InspectionAssignment.revoked_at.is_(None),
                InspectionTask.inspection_date == on_date,
                InspectionTask.canceled_at.is_(None),
            )
        )
        if for_update:
            stmt = stmt.with_for_update(read=True)
        rows = self._session.execute(stmt).all()
        return [(r[0], r[1]) for r in rows]

    # ==================== 志愿者某日锁锚点 ====================
    def ensure_volunteer_day_lock(self, volunteer_user_id: int, on_date: date_) -> None:
        """安全建立 (volunteer, date) 锁记录（幂等 upsert），供随后 *_for_update 锁定。

        联合主键 (volunteer_user_id, inspection_date) 上 INSERT ... ON DUPLICATE KEY UPDATE
        把并发"检查后插入"竞态收敛为单条记录：冲突时以无害自赋值结束，不报错。真实的排班
        串行化由随后的 SELECT ... FOR UPDATE（lock_volunteer_day）在事务内完成。
        """
        stmt = mysql_insert(VolunteerDayLock).values(
            volunteer_user_id=volunteer_user_id, inspection_date=on_date
        )
        stmt = stmt.on_duplicate_key_update(
            volunteer_user_id=stmt.inserted.volunteer_user_id,
            inspection_date=stmt.inserted.inspection_date,
        )
        self._session.execute(stmt)
        self._session.flush()

    def lock_volunteer_day(
        self, volunteer_user_id: int, on_date: date_
    ) -> VolunteerDayLock | None:
        stmt = _for_update(
            select(VolunteerDayLock).where(
                VolunteerDayLock.volunteer_user_id == volunteer_user_id,
                VolunteerDayLock.inspection_date == on_date,
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    # ==================== 截止时间 ====================
    def get_deadline_day(
        self, semester_id: int, on_date: date_
    ) -> SubmissionDeadlineDay | None:
        return self._session.execute(
            select(SubmissionDeadlineDay).where(
                SubmissionDeadlineDay.semester_id == semester_id,
                SubmissionDeadlineDay.inspection_date == on_date,
            )
        ).scalar_one_or_none()

    def get_deadline_day_for_update(
        self, semester_id: int, on_date: date_
    ) -> SubmissionDeadlineDay | None:
        stmt = _for_update(
            select(SubmissionDeadlineDay).where(
                SubmissionDeadlineDay.semester_id == semester_id,
                SubmissionDeadlineDay.inspection_date == on_date,
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_deadline_day_by_id(self, day_id: int) -> SubmissionDeadlineDay | None:
        return self._session.get(SubmissionDeadlineDay, day_id)

    def get_deadline_version(
        self, deadline_day_id: int, version_no: int
    ) -> SubmissionDeadlineVersion | None:
        return self._session.execute(
            select(SubmissionDeadlineVersion).where(
                SubmissionDeadlineVersion.deadline_day_id == deadline_day_id,
                SubmissionDeadlineVersion.version_no == version_no,
            )
        ).scalar_one_or_none()

    def list_deadline_versions(self, deadline_day_id: int) -> list[SubmissionDeadlineVersion]:
        return list(
            self._session.execute(
                select(SubmissionDeadlineVersion)
                .where(SubmissionDeadlineVersion.deadline_day_id == deadline_day_id)
                .order_by(SubmissionDeadlineVersion.version_no)
            )
            .scalars()
            .all()
        )

    def map_current_deadline_version_ids(
        self, days: Sequence[SubmissionDeadlineDay]
    ) -> dict[int, int]:
        """批量解析每个日截止记录**当前生效版本**对应的版本行 id（day.id -> version.id）。

        单次 IN 查询取全部历史版本，再在内存按 day.version 命中，避免逐日 N+1。
        """
        day_list = list(days)
        day_ids = [d.id for d in day_list]
        if not day_ids:
            return {}
        vers = self._session.execute(
            select(SubmissionDeadlineVersion).where(
                SubmissionDeadlineVersion.deadline_day_id.in_(day_ids)
            )
        ).scalars().all()
        by_day: dict[int, dict[int, int]] = {}
        for v in vers:
            by_day.setdefault(v.deadline_day_id, {})[v.version_no] = v.id
        out: dict[int, int] = {}
        for d in day_list:
            vid = by_day.get(d.id, {}).get(d.version)
            if vid is not None:
                out[d.id] = vid
        return out

    def list_deadline_days_by_semester(self, semester_id: int) -> list[SubmissionDeadlineDay]:
        """一次取某学期全部日截止记录，供生成时为缺失日期批量补建（避免逐日查询）。"""
        return list(
            self._session.execute(
                select(SubmissionDeadlineDay).where(
                    SubmissionDeadlineDay.semester_id == semester_id
                )
            )
            .scalars()
            .all()
        )

    def count_active_tasks_on_date(self, semester_id: int, on_date: date_) -> int:
        """某学期某查课日的未取消任务数，供截止配置展示"影响任务数"（技术方案 13.1）。"""
        return int(
            self._session.execute(
                select(func.count())
                .select_from(InspectionTask)
                .where(
                    InspectionTask.semester_id == semester_id,
                    InspectionTask.inspection_date == on_date,
                    InspectionTask.canceled_at.is_(None),
                )
            ).scalar_one()
        )

    # ==================== 截止时考核快照 ====================
    def get_assessment_for_update(self, task_id: int) -> TaskDeadlineAssessment | None:
        stmt = _for_update(
            select(TaskDeadlineAssessment).where(TaskDeadlineAssessment.task_id == task_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_assessments_by_task_ids(
        self, task_ids: Sequence[int]
    ) -> dict[int, TaskDeadlineAssessment]:
        """批量取各任务的截止时考核快照，供列表/详情一次装配（禁 N+1）。"""
        ids = list(task_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(TaskDeadlineAssessment).where(TaskDeadlineAssessment.task_id.in_(ids))
        ).scalars().all()
        return {a.task_id: a for a in rows}

    def list_unsettled_task_ids(
        self,
        semester_id: int,
        *,
        inspection_date: date_ | None = None,
        task_ids: Sequence[int] | None = None,
        limit: int = 500,
    ) -> list[int]:
        """取该学期范围内**尚无**截止时考核快照的任务 id（到期候选，供有界结算）。

        LEFT JOIN task_deadline_assessment 且过滤 a.id IS NULL，即"未结算"任务；再按
        (查课日, id) 升序有界返回，是否真正到期由 service 在任务锁内依旧截止版本判定。
        """
        stmt = (
            select(InspectionTask.id)
            .outerjoin(
                TaskDeadlineAssessment, TaskDeadlineAssessment.task_id == InspectionTask.id
            )
            .where(
                InspectionTask.semester_id == semester_id,
                TaskDeadlineAssessment.id.is_(None),
            )
        )
        if inspection_date is not None:
            stmt = stmt.where(InspectionTask.inspection_date == inspection_date)
        if task_ids:
            stmt = stmt.where(InspectionTask.id.in_(list(task_ids)))
        stmt = stmt.order_by(InspectionTask.inspection_date, InspectionTask.id).limit(limit)
        return [int(r) for r in self._session.execute(stmt).scalars().all()]

    # ==================== 查课提交（P5c）====================
    def get_submission(self, submission_id: int) -> InspectionSubmission | None:
        return self._session.get(InspectionSubmission, submission_id)

    def get_submission_for_update(self, submission_id: int) -> InspectionSubmission | None:
        stmt = _for_update(
            select(InspectionSubmission).where(InspectionSubmission.id == submission_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_submissions_by_task(self, task_id: int) -> list[InspectionSubmission]:
        return list(
            self._session.execute(
                select(InspectionSubmission)
                .where(InspectionSubmission.task_id == task_id)
                .order_by(InspectionSubmission.attempt_no)
            )
            .scalars()
            .all()
        )

    def has_open_submission(self, task_id: int) -> bool:
        """调用者先锁任务；当前读防止 RR 旧快照漏掉刚提交的审核/提交事实。"""
        return (
            self._session.execute(
                select(InspectionSubmission.id)
                .where(
                    InspectionSubmission.task_id == task_id,
                    InspectionSubmission.review_status.in_(
                        [ReviewStatus.PENDING.value, ReviewStatus.APPROVED.value]
                    ),
                )
                .limit(1)
                .with_for_update(read=True)
            )
            .scalar_one_or_none()
            is not None
        )

    def has_approved_submission(self, task_id: int) -> bool:
        """该任务是否已有审核通过提交（据以生成考勤）——已生成考勤者不可再取消（技术方案 51）。"""
        return (
            self._session.execute(
                select(InspectionSubmission.id)
                .where(
                    InspectionSubmission.task_id == task_id,
                    InspectionSubmission.review_status == ReviewStatus.APPROVED.value,
                )
                .limit(1)
                .with_for_update(read=True)
            )
            .scalar_one_or_none()
            is not None
        )

    def max_attempt_no(self, task_id: int) -> int:
        return int(
            self._session.execute(
                select(func.max(InspectionSubmission.attempt_no)).where(
                    InspectionSubmission.task_id == task_id
                )
            ).scalar_one()
            or 0
        )

    def map_submission_flags_by_task_ids(
        self, task_ids: Sequence[int]
    ) -> dict[int, tuple[bool, bool]]:
        """批量派生各任务"有审核通过 / 有待审核"标记，供五态推导（禁 N+1，技术方案 12）。

        单次按任务聚合条件计数即可，不逐任务查询；(has_approved, has_pending)。
        """
        ids = list(task_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(
                InspectionSubmission.task_id,
                func.sum(
                    case(
                        (InspectionSubmission.review_status == ReviewStatus.APPROVED.value, 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (InspectionSubmission.review_status == ReviewStatus.PENDING.value, 1),
                        else_=0,
                    )
                ),
            )
            .where(InspectionSubmission.task_id.in_(ids))
            .group_by(InspectionSubmission.task_id)
        ).all()
        return {int(r[0]): (int(r[1] or 0) > 0, int(r[2] or 0) > 0) for r in rows}

    def has_on_time_submission(self, task_id: int, deadline_at: datetime) -> bool:
        """是否存在**按时**提交（submitted_at ≤ 适用截止，含等于，技术方案 13.3）。

        只看提交时刻不看审核结果：截止前提交后被退回，仍算截止时"有有效提交"，
        不得倒算为未执行（技术方案 13.2、DEVELOPMENT_PLAN 62/64）。
        """
        return (
            self._session.execute(
                select(InspectionSubmission.id)
                .where(
                    InspectionSubmission.task_id == task_id,
                    InspectionSubmission.submitted_at <= deadline_at,
                )
                .limit(1)
            )
            .scalar_one_or_none()
            is not None
        )

    def get_submission_file_ids(self, submission_id: int) -> list[int]:
        return [
            int(fid)
            for fid in self._session.execute(
                select(SubmissionFile.file_id).where(
                    SubmissionFile.submission_id == submission_id
                )
            ).scalars().all()
        ]

    def list_submission_file_ids_by_ids(
        self, submission_ids: Sequence[int]
    ) -> dict[int, list[int]]:
        """批量取各提交的关联文件 id，供装配（禁 N+1）。"""
        ids = list(submission_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(SubmissionFile.submission_id, SubmissionFile.file_id).where(
                SubmissionFile.submission_id.in_(ids)
            )
        ).all()
        out: dict[int, list[int]] = {}
        for sub_id, fid in rows:
            out.setdefault(int(sub_id), []).append(int(fid))
        return out

    def list_my_submissions(
        self,
        params: PageParams,
        *,
        volunteer_user_id: int,
        task_id: int | None = None,
    ) -> tuple[list[InspectionSubmission], int]:
        """本人历史提交（OWN_SUBMISSION 范围）：强制 volunteer_user_id=本人（技术方案 12）。"""
        stmt = select(InspectionSubmission).where(
            InspectionSubmission.volunteer_user_id == volunteer_user_id
        )
        if task_id is not None:
            stmt = stmt.where(InspectionSubmission.task_id == task_id)
        stmt = stmt.order_by(
            InspectionSubmission.submitted_at.desc(), InspectionSubmission.id.desc()
        )
        return _paged(self._session, stmt, params)

    def list_management_submissions(
        self,
        params: PageParams,
        *,
        semester_id: int | None = None,
        date_from: date_ | None = None,
        date_to: date_ | None = None,
        task_id: int | None = None,
        review_status: str | None = None,
    ) -> tuple[list[InspectionSubmission], int]:
        """管理审核列表；先在 SQL 中筛选、计数及分页，再装配提交明细。"""
        stmt = select(InspectionSubmission).join(
            InspectionTask, InspectionTask.id == InspectionSubmission.task_id
        )
        if semester_id is not None:
            stmt = stmt.where(InspectionTask.semester_id == semester_id)
        if date_from is not None:
            stmt = stmt.where(InspectionTask.inspection_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(InspectionTask.inspection_date <= date_to)
        if task_id is not None:
            stmt = stmt.where(InspectionSubmission.task_id == task_id)
        if review_status is not None:
            stmt = stmt.where(InspectionSubmission.review_status == review_status)
        stmt = stmt.order_by(
            InspectionSubmission.submitted_at.desc(), InspectionSubmission.id.desc()
        )
        return _paged(self._session, stmt, params)

    def list_submission_roster_members(
        self, keys: set[tuple[int, int]]
    ) -> list[TaskRosterMember]:
        """一次读取本页提交引用的所有历史名单版本。"""
        if not keys:
            return []
        return list(
            self._session.execute(
                select(TaskRosterMember).where(
                    tuple_(TaskRosterMember.task_id, TaskRosterMember.roster_version).in_(keys)
                )
            ).scalars().all()
        )

    # ==================== 调班申请 ====================
    def get_change_request(self, request_id: int) -> AssignmentChangeRequest | None:
        return self._session.get(AssignmentChangeRequest, request_id)

    def get_change_request_for_update(
        self, request_id: int
    ) -> AssignmentChangeRequest | None:
        stmt = _for_update(
            select(AssignmentChangeRequest).where(AssignmentChangeRequest.id == request_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def has_pending_change_request(self, assignment_id: int) -> bool:
        from app.modules.inspection.models import ChangeRequestStatus

        return (
            self._session.execute(
                select(AssignmentChangeRequest.id)
                .where(
                    AssignmentChangeRequest.assignment_id == assignment_id,
                    AssignmentChangeRequest.status == ChangeRequestStatus.PENDING.value,
                )
                .limit(1)
            )
            .scalar_one_or_none()
            is not None
        )

    def list_change_requests(
        self,
        params: PageParams,
        *,
        assignment_ids: Sequence[int] | None,
        status: str | None,
        requester_user_id: int | None,
    ) -> tuple[list[AssignmentChangeRequest], int]:
        stmt = select(AssignmentChangeRequest)
        conds: list[ColumnElement[bool]] = []
        if assignment_ids is not None:
            conds.append(AssignmentChangeRequest.assignment_id.in_(list(assignment_ids)))
        if status:
            conds.append(AssignmentChangeRequest.status == status)
        if requester_user_id is not None:
            conds.append(AssignmentChangeRequest.request_user_id == requester_user_id)
        if conds:
            stmt = stmt.where(and_(*conds))
        stmt = stmt.order_by(AssignmentChangeRequest.id)
        return _paged(self._session, stmt, params)

    def get_change_request_with_task(
        self, request_id: int
    ) -> tuple[AssignmentChangeRequest, int] | None:
        """联查受派关系取任务 id，供详情响应回填 task_id（避免逐行 N+1）。"""
        row = self._session.execute(
            select(AssignmentChangeRequest, InspectionAssignment.task_id)
            .join(
                InspectionAssignment,
                InspectionAssignment.id == AssignmentChangeRequest.assignment_id,
            )
            .where(AssignmentChangeRequest.id == request_id)
        ).first()
        if row is None:
            return None
        return row[0], int(row[1])

    def list_change_requests_with_task(
        self,
        params: PageParams,
        *,
        status: str | None,
        requester_user_id: int | None,
    ) -> tuple[list[tuple[AssignmentChangeRequest, int]], int]:
        """分页联查申请及其任务 id（元组查询需自行 count + 取行，不走 scalars 的 _paged）。"""
        conds: list[ColumnElement[bool]] = []
        if status:
            conds.append(AssignmentChangeRequest.status == status)
        if requester_user_id is not None:
            conds.append(AssignmentChangeRequest.request_user_id == requester_user_id)
        where = and_(*conds) if conds else None
        base = select(AssignmentChangeRequest, InspectionAssignment.task_id).join(
            InspectionAssignment,
            InspectionAssignment.id == AssignmentChangeRequest.assignment_id,
        )
        if where is not None:
            base = base.where(where)
        count_sub = (
            select(func.count())
            .select_from(AssignmentChangeRequest)
            .join(
                InspectionAssignment,
                InspectionAssignment.id == AssignmentChangeRequest.assignment_id,
            )
        )
        if where is not None:
            count_sub = count_sub.where(where)
        total = int(self._session.execute(count_sub).scalar_one())
        rows = self._session.execute(
            base.order_by(AssignmentChangeRequest.id)
            .limit(params.limit)
            .offset(params.offset)
        ).all()
        return [(r[0], int(r[1])) for r in rows], total


__all__ = ["InspectionRepository"]
