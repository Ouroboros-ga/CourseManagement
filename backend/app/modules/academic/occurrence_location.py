"""指定真实课次的地点覆盖服务：教师本人课程、版本链与任务目的地联动。

固定合同（docs/development/STAFF_ARCHITECTURE_CONTRACT_20261017.md §3 课次地点）：
- 课次键由服务端从正式课表与共享身份解析；教师只能选择本人有效授课关系覆盖的
  教学班课次（LOCAL 不扩散、SHARED 仅已确认映射），不取信客户端 staff_id；
- 共享课程只联动已确认共享 meeting 的同一真实课次；同课次各视图来源时间/节次
  冲突时先拒绝，不按课程名或教室批量改；
- 地点变更与任务生成共用同一覆盖层读取与稳定课次锁（学期行读锁串行化同学期
  生成，覆盖行行锁串行化同课次变更；首次插入的竞争依赖主键唯一、失败整体回滚）；
- 未完成任务更新当前目的地，已取消或已形成考核事实的任务保留原快照；
  地点修订进入课次选择摘要，旧生成预览 409（SELECTION_STALE）。

读取与计划消费的辅助函数只查询、不提交；``change_location`` 是全仓约定的写服务，自己
完成那一次提交并在任何拒绝时整体回滚（``get_db`` 只关闭会话，不隐式提交）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.modules.academic.models import (
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    TeachingClass,
)
from app.modules.academic.occurrence_location_models import (
    OccurrenceLocationChange,
    OccurrenceLocationOverride,
)
from app.modules.academic.staff_repository import StaffRepository
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot
from app.modules.identity.role_scope import business_today
from app.modules.identity.staff_scope import teaching_class_condition
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    TaskScheduleSource,
)
from app.modules.inspection.responsibility import schedule_occurrence, task_occurrences
from app.modules.organization.models import College

if TYPE_CHECKING:
    from app.modules.identity.staff_deps import CurrentStaff

_INT_BOUND = 2**63


def parse_occurrence_key(value: str) -> tuple[str, date]:
    """把 ``s:{shared_meeting_key 或 schedule_id}|{日期}`` 拆为身份与日期；非法即不存在。"""
    meeting, sep, day_text = (value or "").rpartition("|")
    if not sep or not meeting.startswith("s:"):
        raise KeyError(value)
    body = meeting[2:]
    if not body or not meeting[2:].isascii() or len(meeting) > 100:
        raise KeyError(value)
    if (
        not re.fullmatch(r"s:[\w:\-.]{1,60}", meeting)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_text)
    ):
        raise KeyError(value)
    from datetime import datetime as _dt

    try:
        return meeting, _dt.strptime(day_text, "%Y-%m-%d").date()
    except ValueError as exc:  # 例如 2026-02-30
        raise KeyError(value) from exc


class OccurrenceLocationRequest(BaseModel):
    """教师指定课次换教室请求。

    location 为空/null 表示恢复原始课表地点；revision 是客户端所见的当前覆盖版本，
    未曾覆盖（revision=0）也传 0 以参与过期判断，不传则跳过乐观校验。
    """

    model_config = ConfigDict(extra="forbid")

    location: str | None = Field(default=None, max_length=128)
    revision: int | None = Field(default=None, ge=0, le=_INT_BOUND)
    reason: str | None = Field(default=None, max_length=512)


@dataclass(frozen=True)
class OccurrenceLocationSummary:
    occurrence_key: str
    base_location: str | None
    current_location: str | None
    overridden: bool
    revision: int
    affected_task_ids: list[str]


# --------------------------------------------------------------------------- #
# 计划（预览/生成）统一消费覆盖层
# --------------------------------------------------------------------------- #
def load_course_overrides(
    db: Session, keys: set[str] | None = None, *, only_effective: bool = True
) -> dict[str, OccurrenceLocationOverride]:
    stmt = select(OccurrenceLocationOverride)
    if keys is not None:
        keys = {key for key in keys if key}
        if not keys:
            return {}
        stmt = stmt.where(OccurrenceLocationOverride.occurrence_key.in_(keys))
    return {
        row.occurrence_key: row
        for row in db.scalars(stmt)
        if row.location is not None or not only_effective
    }


def apply_course_plan_overrides(db: Session, items) -> None:
    """把已保存的覆盖应用到课程计划条目；任何正式生成路径（含选择式）都必须经过此函数。

    早晚自习计划没有课次键，天然不受影响；同一合并课次有多个键时按键序取第一个。
    """
    entries = load_course_overrides(
        db, {key for item in items for key in getattr(item, "occurrence_keys", []) or []}
    )
    if not entries:
        return
    for item in items:
        for key in sorted(getattr(item, "occurrence_keys", []) or []):
            row = entries.get(key)
            if row is not None and row.location is not None:
                item.classroom_snapshot = row.location
                break


def selection_summary_terms(db: Session, keys: set[str]) -> list[tuple[str, int]]:
    """课次选择摘要的地点修订项 (occurrence_key, revision)；未覆盖的键固定为 0。"""
    rows = load_course_overrides(db, keys, only_effective=False)
    return sorted((key, rows[key].revision if key in rows else 0) for key in keys)


# --------------------------------------------------------------------------- #
# 服务
# --------------------------------------------------------------------------- #
class OccurrenceLocationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._repo = StaffRepository(db)

    # -- 锁与授权 ------------------------------------------------------------- #
    def _guard_actor(self, staff_ref: CurrentStaff, *, lock: bool):
        """核对操作者账号与档案当前有效。

        读入口 ``lock=False``：GET 不应对账号/档案持 ``FOR UPDATE`` 行锁，否则同一教师
        的读取互相串行，并与并发改教室争锁；每次请求仍重新查库，不缓存授权。
        """
        from app.modules.academic.staff_models import FacultyStaff
        from app.modules.identity.models import UserAccount
        from app.modules.identity.repository import IdentityRepository

        if lock:
            account = IdentityRepository(self.db).get_user_by_id_for_update(staff_ref.user.id)
        else:
            account = self.db.scalar(
                select(UserAccount)
                .where(UserAccount.id == staff_ref.user.id)
                .execution_options(populate_existing=True)
            )
        if account is None or account.status != "ACTIVE":
            raise UnauthenticatedError("操作者账号不可用")
        stmt = select(FacultyStaff).where(FacultyStaff.id == staff_ref.staff_id)
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.execute(
            stmt.execution_options(populate_existing=True)
        ).scalar_one()
        if row.status != "ACTIVE":
            raise PermissionDeniedError("教职工档案已停用")
        return account, row

    def _class_row(self, teaching_class_id: int, *, lock: bool = True) -> TeachingClass:
        stmt = select(TeachingClass).where(
            TeachingClass.id == teaching_class_id, TeachingClass.status == "ACTIVE"
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self.db.scalar(
            stmt.execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("教学班不存在或已停用")
        return row

    def _semester_row(self, semester_id: int, *, lock: bool = True) -> Semester:
        stmt = select(Semester).where(Semester.id == semester_id)
        if lock:
            stmt = stmt.with_for_update(read=True)
        row = self.db.scalar(
            stmt.execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("学期不存在")
        return row

    def _assert_teaching_over_day(self, staff_ref: CurrentStaff, teaching_id: int, day: date):
        """锁内复核本人对该教学班、该课次日的有效授课关系；不命中一律不透露存在性。"""
        hit = self.db.scalar(
            select(TeachingClass.id).where(
                TeachingClass.id == teaching_id,
                teaching_class_condition(
                    staff_ref.user.id, occurrence_on=day, as_of=business_today()
                ),
            )
        )
        if hit is None:
            raise NotFoundError("教学班或课次不存在，或不在本人授课范围内")

    # -- 课次键解析 ------------------------------------------------------------ #
    @staticmethod
    def _week_no(semester: Semester, day: date) -> int:
        return ((day - semester.first_monday).days) // 7 + 1

    def _class_occurrence_keys(
        self, semester: Semester, teaching: TeachingClass, day: date
    ) -> dict[str, CourseSchedule]:
        """教学班在该日期可产生的稳定课次键 → 产出该键的本班 ACTIVE 课表行。"""
        week = self._week_no(semester, day)
        if week < 1 or week > semester.total_weeks:
            return {}
        schedules = list(
            self.db.scalars(
                select(CourseSchedule).where(
                    CourseSchedule.teaching_class_id == teaching.id,
                    CourseSchedule.semester_id == teaching.semester_id,
                    CourseSchedule.status == "ACTIVE",
                    CourseSchedule.weekday == day.isoweekday(),
                )
            )
        )
        active_weeks = {
            s.id: {
                week_no
                for week_no in self.db.scalars(
                    select(CourseScheduleWeek.week_no).where(
                        CourseScheduleWeek.schedule_id == s.id
                    )
                )
            }
            for s in schedules
        }
        out: dict[str, CourseSchedule] = {}
        for s in schedules:
            if week in active_weeks[s.id]:
                out[schedule_occurrence(s, day)] = s
        return out

    def _same_real_meeting_schedules(
        self, teaching: TeachingClass, meeting: str, day: date, week: int
    ) -> list[CourseSchedule]:
        """同校、该学期内、当前真实会产生 meeting|day 这一课次的全部 ACTIVE 课表行。

        两种来源（并集即定义）：已确认共享身份的组（meeting 即 shared_meeting_key），
        或尚未进入共享期的本地行（meeting 即 s:{自身 id}）；未进入共享期的行被显式
        从本地分支排除，防止共享键误扩到未确认映射。
        """
        school_id = self.db.scalar(
            select(College.school_id).where(College.id == teaching.college_id)
        )
        body = meeting[2:]
        branches = [
            and_(
                CourseSchedule.shared_meeting_key == meeting,
                CourseSchedule.shared_identity_from.is_not(None),
                CourseSchedule.shared_identity_from <= day,
            )
        ]
        if body.isascii() and body.isdigit() and 0 < int(body) < _INT_BOUND:
            branches.append(
                and_(
                    CourseSchedule.id == int(body),
                    or_(
                        CourseSchedule.shared_meeting_key.is_(None),
                        CourseSchedule.shared_identity_from.is_(None),
                        CourseSchedule.shared_identity_from > day,
                    ),
                )
            )
        stmt = (
            select(CourseSchedule)
            .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
            .join(College, College.id == TeachingClass.college_id)
            .where(
                CourseSchedule.semester_id == teaching.semester_id,
                CourseSchedule.status == "ACTIVE",
                TeachingClass.status == "ACTIVE",
                College.status == "ACTIVE",
                College.school_id == school_id,
                or_(*branches),
            )
        )
        rows = list(
            self.db.scalars(stmt.order_by(CourseSchedule.id).execution_options(populate_existing=True))
        )
        filtered = []
        for s in rows:
            if s.weekday != day.isoweekday():
                continue
            if not self.db.scalar(
                select(CourseScheduleWeek.id).where(
                    CourseScheduleWeek.schedule_id == s.id, CourseScheduleWeek.week_no == week
                )
            ):
                continue
            filtered.append(s)
        return filtered

    @staticmethod
    def _assert_meeting_consistent(rows: list[CourseSchedule]) -> None:
        if len(rows) <= 1:
            return
        shapes = {(s.weekday, s.start_period, s.end_period) for s in rows}
        if len(shapes) > 1:
            raise ConflictError(
                ErrorCode.STATE_CONFLICT,
                "同一真实课次在不同学院视图的时间或节次不一致，请先核对共享映射，不能按单一视图改教室",
            )

    # -- 读（GET） ------------------------------------------------------------- #
    def location_summary(
        self, staff_ref: CurrentStaff, teaching_class_id: int, occurrence_key: str
    ) -> OccurrenceLocationSummary:
        try:
            meeting, day = parse_occurrence_key(occurrence_key)
        except KeyError as exc:
            raise NotFoundError("课次键无效") from exc
        self._guard_actor(staff_ref, lock=False)
        teaching = self._class_row(teaching_class_id, lock=False)
        semester = self._semester_row(teaching.semester_id, lock=False)
        self._assert_teaching_over_day(staff_ref, teaching.id, day)
        keys = self._class_occurrence_keys(semester, teaching, day)
        if occurrence_key not in keys:
            raise NotFoundError("该教学班在此日期没有该真实课次")
        own = keys[occurrence_key]
        week = self._week_no(semester, day)
        self._assert_meeting_consistent(
            self._same_real_meeting_schedules(teaching, meeting, day, week)
        )
        affected = self._collect_updatable_tasks(
            semester.id, day, occurrence_key, lock=False
        )
        row = self.db.scalar(
            select(OccurrenceLocationOverride).where(
                OccurrenceLocationOverride.occurrence_key == occurrence_key
            )
        )
        base = own.classroom
        return OccurrenceLocationSummary(
            occurrence_key=occurrence_key,
            base_location=base,
            current_location=(row.location if row and row.location is not None else base),
            overridden=bool(row and row.location is not None),
            revision=row.revision if row else 0,
            affected_task_ids=[str(t.id) for t in affected],
        )

    # -- 写（PATCH） ------------------------------------------------------------ #
    def change_location(
        self,
        staff_ref: CurrentStaff,
        teaching_class_id: int,
        occurrence_key: str,
        body: OccurrenceLocationRequest,
        request_id: str | None = None,
    ) -> OccurrenceLocationSummary:
        """单次提交覆盖行、变更链、任务目的地与审计；任何拒绝都整体回滚。

        ``get_db`` 只负责关闭会话，不隐式提交（技术方案 5.1），所以写服务必须自己完成
        那一次提交；否则接口返回成功而数据随请求会话一起被回滚。
        """
        try:
            meeting, day = parse_occurrence_key(occurrence_key)
        except KeyError as exc:
            raise NotFoundError("课次键无效") from exc
        target = body.location.strip() if body.location else None
        if not target:
            target = None
        attempt = 0
        while True:
            try:
                summary = self._change_once(
                    staff_ref, teaching_class_id, occurrence_key, meeting,
                    day, target, body, request_id,
                )
            except IntegrityError:
                self.db.rollback()
                attempt += 1
                if attempt >= 3:
                    raise ConflictError(
                        ErrorCode.STATE_CONFLICT, "并发修改课次地点冲突，请重试"
                    ) from None
                continue
            except Exception:
                self.db.rollback()
                raise
            self.db.commit()
            return summary
    def _change_once(
        self,
        staff_ref: CurrentStaff,
        teaching_class_id: int,
        occurrence_key: str,
        meeting: str,
        day: date,
        target: str | None,
        body: OccurrenceLocationRequest,
        request_id: str | None,
    ) -> OccurrenceLocationSummary:
        account, _profile = self._guard_actor(staff_ref, lock=True)
        teaching = self._class_row(teaching_class_id)
        semester = self._semester_row(teaching.semester_id)
        if semester.status != "ACTIVE":
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期已归档，不能修改课次地点")
        self._assert_teaching_over_day(staff_ref, teaching.id, day)
        keys = self._class_occurrence_keys(semester, teaching, day)
        if occurrence_key not in keys:
            raise NotFoundError("该教学班在此日期没有该真实课次")
        own = keys[occurrence_key]
        week = self._week_no(semester, day)
        peers = [s for s in self._same_real_meeting_schedules(teaching, meeting, day, week)]
        if all(s.teaching_class_id != teaching.id for s in peers):
            # 其他视图的课表与本人教学班不再产生同一课次 —— 映射漂移，拒绝。
            raise ConflictError(
                ErrorCode.STATE_CONFLICT,
                "共享映射与本人教学班不一致，请先核对再修改地点",
            )
        self._assert_meeting_consistent(peers)

        row = self.db.scalar(
            select(OccurrenceLocationOverride)
            .where(OccurrenceLocationOverride.occurrence_key == occurrence_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            self.db.add(
                OccurrenceLocationOverride(
                    occurrence_key=occurrence_key,
                    school_id=self.db.scalar(
                        select(College.school_id).where(College.id == teaching.college_id)
                    ),
                    location=None,
                    revision=0,
                    effective_date=day,
                    updated_by=None,
                )
            )
            self.db.flush()
            row = self.db.scalar(
                select(OccurrenceLocationOverride)
                .where(OccurrenceLocationOverride.occurrence_key == occurrence_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                # 主键唯一竞争由外层 IntegrityError 重试接管；仅防类型收窄的兜底路径。
                raise ConflictError(ErrorCode.STATE_CONFLICT, "课次地点覆盖行创建失败，请重试")
        if body.revision is not None and row.revision != body.revision:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "课次地点已被他人修改，请刷新后重试"
            )

        previous = row.location
        row.revision += 1
        row.location = target
        row.updated_by = account.id
        self.db.add(
            OccurrenceLocationChange(
                occurrence_key=occurrence_key,
                revision_no=row.revision,
                previous_location=previous,
                new_location=target,
                effective_date=day,
                changed_by=account.id,
                reason=body.reason,
            )
        )
        affected = self._collect_updatable_tasks(semester.id, day, occurrence_key, lock=True)
        affected_ids: list[str] = []
        for task in affected:
            task.classroom_snapshot = (
                target if target is not None else self._task_base_location(task)
            )
            affected_ids.append(str(task.id))
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_user_id=account.id,
                action="academic.occurrence.location_change",
                resource_type="occurrence_location",
                resource_id=occurrence_key[:64],
                before_json=scoped_snapshot(
                    {"location": previous, "revision": row.revision - 1},
                    teaching.college_id,
                ),
                after_json=scoped_snapshot(
                    {
                        "location": target,
                        "revision": row.revision,
                        "effective_date": day.isoformat(),
                        "affected_task_ids": affected_ids,
                    },
                    teaching.college_id,
                ),
                reason=body.reason,
                request_id=request_id,
            )
        )
        self.db.flush()
        base = own.classroom
        return OccurrenceLocationSummary(
            occurrence_key=occurrence_key,
            base_location=base,
            current_location=target if target is not None else base,
            overridden=target is not None,
            revision=row.revision,
            affected_task_ids=affected_ids,
        )

    # -- 未完成任务目的地 ------------------------------------------------------- #
    def _collect_updatable_tasks(
        self, semester_id: int, day: date, occurrence_key: str, *, lock: bool
    ) -> list[InspectionTask]:
        """本学期该日期、未取消且引用该课次的任务。

        课次键只在同一学期的课表内产生，因此先按 (学期, 日期) 走索引收窄，再逐条核对
        键集合；不能扫描部署内所有历史任务，也不能只按日期跨学期联动。
        """
        stmt = (
            select(InspectionTask)
            .where(
                InspectionTask.semester_id == semester_id,
                InspectionTask.inspection_date == day,
                InspectionTask.canceled_at.is_(None),
            )
            .order_by(InspectionTask.id)
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        tasks = list(self.db.scalars(stmt))
        out: list[InspectionTask] = []
        for task in tasks:
            if occurrence_key not in task_occurrences(self.db, task):
                continue
            # 已取消任务目的地不自动改写；已形成考核事实/考勤的任务保留现场快照。
            if self.db.scalar(
                select(InspectionSubmission.id)
                .where(
                    InspectionSubmission.task_id == task.id,
                    InspectionSubmission.review_status == ReviewStatus.APPROVED.value,
                )
                .limit(1)
            ):
                continue
            if self.db.scalar(
                select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id).limit(1)
            ):
                continue
            out.append(task)
        return out

    def _task_base_location(self, task: InspectionTask) -> str | None:
        schedule_id = task.course_schedule_id
        if schedule_id is None:
            ids = self.db.scalars(
                select(TaskScheduleSource.course_schedule_id).where(
                    TaskScheduleSource.task_id == task.id
                )
            ).all()
            schedule_id = min(ids) if ids else None
        if schedule_id is None:
            return task.classroom_snapshot
        classroom = self.db.scalar(
            select(CourseSchedule.classroom).where(CourseSchedule.id == schedule_id)
        )
        return classroom if classroom else task.classroom_snapshot


__all__ = [
    "OccurrenceLocationRequest",
    "OccurrenceLocationSummary",
    "OccurrenceLocationService",
    "apply_course_plan_overrides",
    "selection_summary_terms",
    "load_course_overrides",
    "parse_occurrence_key",
]
