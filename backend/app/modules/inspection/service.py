"""查课任务与排班服务（Wave 2）：任务"预览→生成"两步、幂等、名单快照冻结、
首次建当日截止记录、有界规模、整批单事务原子（技术方案 10、11.1、13.1、15）。

事务与守卫约定（与 academic/importer 一致，PERMISSIONS.md 13.2）：
- 同步 Session 由依赖注入；写路径成功末尾**单次 commit**，失败抛 AppError 由依赖回滚；
- 生成在同一事务内先 `SELECT ... FOR UPDATE` 锁定学期：既校验 ACTIVE，又把"同学期并发
  生成"串行化，配合 task_key 唯一约束实现幂等（重复键跳过而非报错），保证整批全成或全回滚；
- 事务内重读操作者有效权限纵深复核；审计 append-only 同事务写入。

冻结纪律（DEVELOPMENT_PLAN 6）：默认截止时刻、规模上限、时区偏移一律来自可配置
`Settings`，不写死学校制度数值。
"""

from __future__ import annotations
import hashlib
import re

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as date_
from datetime import datetime, time, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.common.pagination import PageParams
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.core.permissions import RoleCode
from app.modules.academic.calendar import resolve_teaching_day
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    OverrideType,
    Semester,
    SemesterStatus,
    Student,
    TeachingClass,
    TeachingClassStudent,
    VolunteerQualification,
)
from app.modules.academic.repository import AcademicRepository
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
    AttendanceType,
)
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.identity.models import Role, UserAccount, UserRole, UserStatus
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.inspection import permissions as perms
from app.modules.inspection.course_policy import is_course_exempt, is_physical_education
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    AssignMethod,
    ChangeRequestStatus,
    DeadlineAssessmentResult,
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    InspectionType,
    ReviewStatus,
    SubmissionAbnormalItem,
    SubmissionDeadlineDay,
    SubmissionDeadlineVersion,
    SubmissionFile,
    TaskDeadlineAssessment,
    TaskRosterMember,
    TaskRosterVersion,
)
from app.modules.inspection.repository import InspectionRepository
from app.modules.inspection.scheduling.loader import REASONS, load_snapshot
from app.modules.inspection.scheduling.planner import plan_assignments
from app.modules.inspection.scheduling.validation import validate_plan
from app.modules.inspection.schemas import (
    REASON_COURSE_NOT_INSPECTABLE,
    REASON_DAY_CAP,
    REASON_DEADLINE_EARLY,
    REASON_NO_QUALIFICATION,
    REASON_NOT_VOLUNTEER,
    REASON_OWN_CLASS,
    REASON_SELF_CLASS,
    REASON_TASK_CONFLICT,
    AssignmentSetRequest,
    AutoAssignRequest,
    AutoAssignResultResponse,
    ChangeRequestCreateRequest,
    ChangeRequestResponse,
    ChangeRequestReviewRequest,
    DeadlineAssessmentBrief,
    DeadlineDayUpdateRequest,
    DeadlineSettleRequest,
    DeadlineSettleResultResponse,
    ExpectedCountUpdateRequest,
    GeneratedTaskBrief,
    GeneratePreviewResponse,
    GenerateResultResponse,
    InspectionGenerateRequest,
    InspectionTaskResponse,
    InspectionTaskUpdateRequest,
    ManagementSubmissionResponse,
    ManagementSubmissionTaskBrief,
    PlannedAssignment,
    PlannedTaskBrief,
    RosterVersionCreateRequest,
    RosterVersionResponse,
    SettledTaskBrief,
    SubmissionAbnormalItemResponse,
    SubmissionCreateRequest,
    SubmissionDeadlineDayResponse,
    SubmissionDeadlineDefaultResponse,
    SubmissionDeadlineVersionResponse,
    SubmissionResponse,
    SubmissionReviewRequest,
    TaskAssignmentBrief,
    TaskCancelRequest,
    TaskRosterMemberResponse,
    TaskRosterResponse,
    UnassignedTaskBrief,
)
from app.modules.report.source_revision import SourceRevisionService


# --------------------------------------------------------------------------- #
# 计划条目（预览与生成共用；不落库，生成时才物化为任务 + 名单快照）
# --------------------------------------------------------------------------- #
@dataclass
class PlanItem:
    task_key: str
    semester_id: int
    inspection_date: date_
    week_no: int
    inspection_type: str
    start_period: int
    end_period: int
    course_schedule_id: int | None
    teaching_class_id: int | None
    administrative_class_id: int | None
    course_name_snapshot: str | None
    class_name_snapshot: str | None
    classroom_snapshot: str | None
    require_photo_snapshot: bool
    student_ids: list[int] = field(default_factory=list)
    roster: list[TaskRosterMember] = field(default_factory=list)
    constituent_schedule_ids: list[int] = field(default_factory=list)


@dataclass
class _VolProfile:
    """排班候选志愿者的资格判定所需快照（Wave 3a）。"""

    user_id: int
    status: str
    is_volunteer: bool
    student_id: int | None
    admin_class_id: int | None


def _date_for_week_first_monday(first_monday: date_, week_no: int, weekday: int) -> date_:
    """周次 + 星期(1=周一..7=周日) → 日历日期。"""
    return first_monday + timedelta(days=(week_no - 1) * 7 + (weekday - 1))


def _week_no_for_date(first_monday: date_, on_date: date_) -> int:
    """日历日期 → 周次（以首周一为第 1 周基准）。"""
    return (on_date - first_monday).days // 7 + 1


class InspectionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = InspectionRepository(session)
        self._academic = AcademicRepository(session)
        self._identity = IdentityRepository(session)

    # ================================================================== #
    # 守卫 / 审计 / 数据范围
    # ================================================================== #
    def _require(self, actor_user_id: int, code: str) -> None:
        """事务内锁定操作者并重读有效权限纵深复核（PERMISSIONS.md 13.2）。"""
        actor = self._identity.get_user_by_id_for_update(actor_user_id)
        if actor is None or not actor.is_active:
            raise UnauthenticatedError("操作者账号不可用")
        if code not in set(self._identity.list_effective_permissions(actor_user_id)):
            raise PermissionDeniedError()

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        resource_type: str,
        resource_id: str,
        after: dict | None,
        reason: str | None,
        request_id: str | None,
        before: dict | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_json=before,
                after_json=after,
                reason=reason,
                request_id=request_id,
            )
        )
        self._session.flush()

    def _scope_filter(self, actor: CurrentUser, *, force_assigned: bool = False):
        """构造任务可见性 select：管理范围全部可见，志愿者仅本人受派任务。

        force_assigned=True 用于 /me 端点，无论角色一律限定为本人受派任务。
        """
        if force_assigned:
            stmt = select(InspectionTask)
            subq = select(InspectionAssignment.task_id).where(
                InspectionAssignment.volunteer_user_id == actor.id,
                InspectionAssignment.revoked_at.is_(None),
            )
            return stmt.where(InspectionTask.id.in_(subq))
        scope = perms.resolve_scope(actor.roles)
        if perms.is_management_scope(scope):
            return None  # 管理范围：不加可见性谓词（V1.0 无学院分区）
        stmt = select(InspectionTask)
        subq = select(InspectionAssignment.task_id).where(
            InspectionAssignment.volunteer_user_id == actor.id,
            InspectionAssignment.revoked_at.is_(None),
        )
        return stmt.where(InspectionTask.id.in_(subq))

    # ================================================================== #
    # 计划构建（预览与生成共用，保证两步口径一致）
    # ================================================================== #
    def _require_active_semester(self, semester_id: int) -> Semester:
        sem = self._academic.get_semester_for_update(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != SemesterStatus.ACTIVE.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期已归档，禁止生成任务")
        return sem

    def _resolve_dates(
        self, sem: Semester, week_nos: Sequence[int] | None, date_from: date_ | None,
        date_to: date_ | None,
    ) -> list[tuple[date_, int]]:
        """候选 (date, week_no)：week_nos 整周 7 天与 date_from..date_to 逐日并集，升序去重。"""
        candidates: dict[date_, int] = {}
        if week_nos:
            for w in week_nos:
                if w < 1 or w > sem.total_weeks:
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        f"周次 {w} 超出学期范围(1..{sem.total_weeks})",
                        http_status=422,
                        field_errors={"week_nos": list(week_nos)},
                    )
                for wd in range(1, 8):
                    d = _date_for_week_first_monday(sem.first_monday, w, wd)
                    candidates.setdefault(d, w)
        if date_from is not None and date_to is not None:
            if date_from < sem.start_date or date_to > sem.end_date:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "日期范围超出学期起止",
                    http_status=422,
                    field_errors={"date_from": str(date_from), "date_to": str(date_to)},
                )
            cur = date_from
            while cur <= date_to:
                candidates.setdefault(cur, _week_no_for_date(sem.first_monday, cur))
                cur += timedelta(days=1)
        return sorted(candidates.items(), key=lambda kv: kv[0])

    def _load_overrides(self, semester_id: int) -> dict[date_, CalendarOverride]:
        return {c.date: c for c in self._academic.list_calendar_overrides(semester_id)}

    def _attach_rosters(self, items: list[PlanItem]) -> list[PlanItem]:
        """批量取学生与行政班，回填每个计划条目的冻结名单快照。"""
        all_ids = {sid for it in items for sid in it.student_ids}
        if not all_ids:
            return items
        students = {
            s.id: s
            for s in self._session.execute(
                select(Student).where(Student.id.in_(list(all_ids)))
            ).scalars().all()
        }
        ac_ids = {
            s.administrative_class_id for s in students.values() if s.administrative_class_id
        }
        acs = (
            {
                a.id: a
                for a in self._session.execute(
                    select(AdministrativeClass).where(AdministrativeClass.id.in_(list(ac_ids)))
                ).scalars().all()
            }
            if ac_ids
            else {}
        )
        for it in items:
            roster: list[TaskRosterMember] = []
            for sid in it.student_ids:
                s = students.get(sid)
                if s is None:
                    continue
                ac = acs.get(s.administrative_class_id) if s.administrative_class_id else None
                roster.append(
                    TaskRosterMember(
                        student_id=s.id,
                        student_no=s.student_no,
                        name=s.name,
                        class_name_snapshot=ac.class_name if ac else None,
                        grade_year_snapshot=ac.grade_year if ac else None,
                    )
                )
            it.roster = roster
        return items

    @staticmethod
    def _task_key(
        semester_id: int, on_date: date_, itype: str, start: int, end: int, target: str
    ) -> str:
        return f"{semester_id}|{on_date.isoformat()}|{itype}|{start}-{end}|{target}"

    def _check_scale(self, planned: int) -> int:
        settings = get_settings()
        if planned > settings.inspection_generate_max_tasks:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"选择范围过大：计划生成 {planned} 个任务，超过单次上限 "
                f"{settings.inspection_generate_max_tasks}，请缩小范围",
                http_status=422,
                field_errors={"planned_tasks": planned},
            )
        return settings.inspection_generate_max_tasks

    # ================================================================== #
    # 预览（只读计算，不写任何表）
    # ================================================================== #
    def preview(
        self, actor: CurrentUser, body: InspectionGenerateRequest
    ) -> GeneratePreviewResponse:
        self._require(actor.id, perms.GENERATE_PERMISSION)
        max_tasks = 0
        # 只读预览用短事务：读取即隐式开事务，结尾统一 rollback 释放（不写库）。
        try:
            sem = self._get_active_semester_read(body.semester_id)
            items = self._build_plan_no_semlock(sem, body)
            planned = len(items)
            max_tasks = self._check_scale(planned)
            existing = self._repo.find_task_ids_by_keys([it.task_key for it in items])
            new_count = sum(1 for it in items if it.task_key not in existing)
            dates = {it.inspection_date for it in items}
            sample = sorted(items, key=lambda i: (i.inspection_date, i.task_key))[:20]
            return GeneratePreviewResponse(
                semester_id=sem.id,
                inspection_type=body.inspection_type,
                task_count=planned,
                new_task_count=new_count,
                existing_task_count=planned - new_count,
                date_count=len(dates),
                student_total=sum(len(i.student_ids) for i in items),
                within_limit=True,
                max_tasks=max_tasks,
                sample=[self._to_planned_brief(i) for i in sample],
                sample_truncated=planned > len(sample),
            )
        finally:
            self._session.rollback()

    def _get_active_semester_read(self, semester_id: int) -> Semester:
        sem = self._academic.get_semester(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != SemesterStatus.ACTIVE.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "学期已归档，禁止生成任务")
        return sem

    @staticmethod
    def _to_planned_brief(it: PlanItem) -> PlannedTaskBrief:
        return PlannedTaskBrief(
            task_key=it.task_key,
            inspection_date=it.inspection_date,
            week_no=it.week_no,
            inspection_type=it.inspection_type,
            start_period=it.start_period,
            end_period=it.end_period,
            class_name_snapshot=it.class_name_snapshot,
            course_name_snapshot=it.course_name_snapshot,
            classroom_snapshot=it.classroom_snapshot,
            expected_count=len(it.student_ids),
        )

    # ================================================================== #
    # 生成（整批单事务原子，幂等跳过既有）
    # ================================================================== #
    def generate(
        self, actor: CurrentUser, body: InspectionGenerateRequest, request_id: str | None
    ) -> GenerateResultResponse:
        if body.occurrences is not None:
            # 鉴权依赖可能已打开 RR 旧快照。精确生成开启独立 RC 事务，在学期锁内
            # 重建选择范围，读取刚提交的课表/名单修改，而非沿用旧读视图。
            self._session.rollback()
            self._session.connection(execution_options={"isolation_level": "READ COMMITTED"})
        self._require(actor.id, perms.GENERATE_PERMISSION)
        sem = self._require_active_semester(body.semester_id)  # FOR UPDATE 串行化同学期生成
        items = self._build_plan_no_semlock(sem, body)
        planned = len(items)
        self._check_scale(planned)

        attempt = 0
        while True:
            try:
                return self._materialize(sem, body, items, actor.id, request_id)
            except IntegrityError:
                self._session.rollback()
                attempt += 1
                if attempt >= 3:
                    raise ConflictError(
                        ErrorCode.STATE_CONFLICT, "并发生成冲突，请重试"
                    ) from None
                # 重新锁定学期、重算计划并复核既有键（幂等），再试一次物化+提交。
                sem = self._require_active_semester(body.semester_id)
                items = self._build_plan_no_semlock(sem, body)

    def _build_plan_no_semlock(
        self, sem: Semester, body: InspectionGenerateRequest
    ) -> list[PlanItem]:
        if body.occurrences is not None:
            from app.modules.inspection.course_occurrences import select_occurrences

            return select_occurrences(self, sem, body)
        if body.inspection_type == InspectionType.COURSE.value:
            return self._build_course_plan_core(sem, body)
        return self._build_study_plan_core(sem, body)

    def _materialize(
        self,
        sem: Semester,
        body: InspectionGenerateRequest,
        items: list[PlanItem],
        actor_user_id: int,
        request_id: str | None,
    ) -> GenerateResultResponse:
        existing = self._repo.find_task_ids_by_keys([it.task_key for it in items])
        new_items = [it for it in items if it.task_key not in existing]

        for it in new_items:
            task = InspectionTask(
                task_key=it.task_key,
                semester_id=it.semester_id,
                inspection_date=it.inspection_date,
                week_no=it.week_no,
                inspection_type=it.inspection_type,
                start_period=it.start_period,
                end_period=it.end_period,
                course_schedule_id=it.course_schedule_id,
                teaching_class_id=it.teaching_class_id,
                administrative_class_id=it.administrative_class_id,
                course_name_snapshot=it.course_name_snapshot,
                class_name_snapshot=it.class_name_snapshot,
                classroom_snapshot=it.classroom_snapshot,
                require_photo_snapshot=it.require_photo_snapshot,
                expected_count_snapshot=len(it.roster),
                expected_count_current=len(it.roster),
                roster_version=1,
                lock_version=0,
            )
            self._repo.add(task)
            self._repo.flush()  # 取得 task.id
            rv = TaskRosterVersion(
                task_id=task.id, version_no=1, reason=body.reason, created_by=actor_user_id
            )
            self._repo.add(rv)
            for m in it.roster:
                m.task_id = task.id
                m.roster_version = 1
                self._repo.add(m)
            self._repo.flush()

        seeded = self._seed_deadlines(sem.id, items, actor_user_id)

        self._audit(
            actor_user_id=actor_user_id,
            action="inspection.task.generate",
            resource_type="inspection_task",
            resource_id=f"{sem.id}:batch",
            after={
                "inspection_type": body.inspection_type,
                "created": len(new_items),
                "existed": len(existing),
                "total_planned": len(items),
                "deadline_days_seeded": seeded,
            },
            reason=body.reason,
            request_id=request_id,
        )
        selected_tasks = list(self._session.execute(
            select(InspectionTask).where(
                InspectionTask.task_key.in_([it.task_key for it in items])
            ).order_by(InspectionTask.inspection_date, InspectionTask.id)
        ).scalars())
        views = self._assemble_tasks(selected_tasks)
        assignments = self._repo.list_assignments_by_task_ids([t.id for t in selected_tasks])
        results = [GeneratedTaskBrief(
            task_id=view.id, created=view.task_key not in existing, status=view.status,
            assignment_id=str(assignments[task.id].id) if task.id in assignments else None,
        ) for task, view in zip(selected_tasks, views, strict=True)]
        assignable = [r.task_id for r in results
                      if r.assignment_id is None and r.status in {"待执行", "已逾期"}]
        # 单一提交点：任务 + 名单快照 + 截止记录 + 审计同事务原子生效。
        self._session.commit()
        return GenerateResultResponse(
            semester_id=sem.id,
            inspection_type=body.inspection_type,
            created=len(new_items),
            existed=len(existing),
            total_planned=len(items),
            deadline_days_seeded=seeded,
            tasks=results,
            assignable_task_ids=assignable,
        )

    def _seed_deadlines(self, semester_id: int, items: list[PlanItem], actor_user_id: int) -> int:
        """为计划覆盖但尚无日截止记录的查课日，按当前默认时刻生成 v1（技术方案 13.1）。"""
        dates = {it.inspection_date for it in items}
        if not dates:
            return 0
        have = {d.inspection_date for d in self._repo.list_deadline_days_by_semester(semester_id)}
        missing = sorted(dates - have)
        if not missing:
            return 0
        deadline_naive = self._default_deadline_naive()
        for d in missing:
            day = SubmissionDeadlineDay(
                semester_id=semester_id,
                inspection_date=d,
                deadline_at=deadline_naive(d),
                version=1,
                updated_by=actor_user_id,
                reason="首次为该查课日生成任务时按默认时刻创建",
            )
            self._repo.add(day)
            self._repo.flush()  # 取得 day.id 供版本行外键
            ver = SubmissionDeadlineVersion(
                deadline_day_id=day.id,
                version_no=1,
                deadline_at=day.deadline_at,
                changed_by=actor_user_id,
                reason="初始默认",
            )
            self._repo.add(ver)
        self._repo.flush()
        return len(missing)

    def _default_deadline_naive(self):
        settings = get_settings()
        hh, mm = 22, 0
        raw = (settings.default_submission_deadline_time or "").strip()
        try:
            t = time.fromisoformat(raw)
            hh, mm = t.hour, t.minute
        except ValueError:
            pass
        offset = timedelta(hours=settings.app_utc_offset_hours)

        def _build(d: date_) -> datetime:
            # 本地墙上时钟组合后转 naive-UTC（与 utcnow() 同域可比）。
            local_naive = datetime.combine(d, time(hh, mm))
            return local_naive - offset

        return _build

    # ================================================================== #
    # 读取：列表 / 详情 / 本人任务 / 名单
    # ================================================================== #
    def list_tasks(
        self,
        actor: CurrentUser,
        params: PageParams,
        *,
        semester_id: int | None,
        inspection_date: date_ | None,
        week_no: int | None,
        inspection_type: str | None,
        teaching_class_id: int | None = None,
        administrative_class_id: int | None = None,
        include_canceled: bool,
    ) -> dict:
        self._require(actor.id, perms.READ_PERMISSION)
        scope = self._scope_filter(actor)
        rows, total = self._repo.list_tasks(
            params,
            scope_filter=scope,
            semester_id=semester_id,
            inspection_date=inspection_date,
            week_no=week_no,
            inspection_type=inspection_type,
            teaching_class_id=teaching_class_id,
            administrative_class_id=administrative_class_id,
            include_canceled=include_canceled,
        )
        dto = self._assemble_tasks(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_task(self, actor: CurrentUser, task_id: int) -> InspectionTaskResponse:
        self._require(actor.id, perms.READ_PERMISSION)
        scope = self._scope_filter(actor)
        task = self._repo.get_task_scoped(task_id, scope_filter=scope)
        if task is None:
            raise NotFoundError("查课任务不存在或不可见")
        return self._assemble_tasks([task])[0]

    def my_tasks(
        self, actor: CurrentUser, params: PageParams, *, include_canceled: bool
    ) -> dict:
        # /me 无论角色一律强制限定为本人受派任务。
        self._require(actor.id, perms.READ_PERMISSION)
        scope = self._scope_filter(actor, force_assigned=True)
        rows, total = self._repo.list_tasks(
            params, scope_filter=scope, include_canceled=include_canceled
        )
        dto = self._assemble_tasks(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_roster(
        self, actor: CurrentUser, task_id: int, roster_version: int | None
    ) -> TaskRosterResponse:
        self._require(actor.id, perms.ROSTER_READ_PERMISSION)
        scope = self._scope_filter(actor)
        task = self._repo.get_task_scoped(task_id, scope_filter=scope)
        if task is None:
            raise NotFoundError("查课任务不存在或不可见")
        version = roster_version if roster_version is not None else task.roster_version
        members = self._repo.list_roster_members(task.id, version)
        return TaskRosterResponse(
            task_id=task.id,
            roster_version=version,
            items=[
                TaskRosterMemberResponse(
                    student_id=m.student_id,
                    student_no=m.student_no,
                    name=m.name,
                    class_name_snapshot=m.class_name_snapshot,
                    grade_year_snapshot=m.grade_year_snapshot,
                )
                for m in members
            ],
        )

    def _assemble_tasks(self, tasks: Sequence[InspectionTask]) -> list[InspectionTaskResponse]:
        """批量装配任务响应：一次性取受派 + 日截止 + 考核快照 + 当前版本 id，
        避免逐行查询（技术方案 12）；派生五种当前状态并回填截止上下文。"""
        ids = [t.id for t in tasks]
        assignments = self._repo.list_assignments_by_task_ids(ids)
        assessments = self._repo.list_assessments_by_task_ids(ids)
        sub_flags = self._repo.map_submission_flags_by_task_ids(ids)
        deadline_by_date: dict[tuple[int, date_], SubmissionDeadlineDay] = {}
        sem_ids = {t.semester_id for t in tasks}
        for sid in sem_ids:
            for d in self._repo.list_deadline_days_by_semester(sid):
                deadline_by_date[(sid, d.inspection_date)] = d
        cur_ver_ids = self._repo.map_current_deadline_version_ids(
            list(deadline_by_date.values())
        )
        result: list[InspectionTaskResponse] = []
        for t in tasks:
            day = deadline_by_date.get((t.semester_id, t.inspection_date))
            assessment = assessments.get(t.id)
            version_id = (
                assessment.deadline_version_id
                if assessment is not None
                else (cur_ver_ids.get(day.id) if day is not None else None)
            )
            result.append(
                self._to_task_dto(
                    t,
                    assignments.get(t.id),
                    day,
                    assessment,
                    version_id,
                    sub_flags.get(t.id, (False, False)),
                )
            )
        return result

    @staticmethod
    def _derive_status(
        task: InspectionTask,
        assignment: InspectionAssignment | None,  # noqa: ARG004 - 保留签名，数据范围已在谓词层
        day: SubmissionDeadlineDay | None,
        submission_flags: tuple[bool, bool] = (False, False),
    ) -> str:
        """五种当前状态派生（技术方案 12、13.3）。

        优先级：已取消 → 已完成（有审核通过提交）→ 待审核（有待审核提交）→ 已逾期 → 待执行。

        ``submission_flags`` = (has_approved, has_pending)：由批量提交聚合得出，避免逐任务查询。
        截止时刻维度沿用 Wave 3c：无待审核/审核通过提交且服务端时间**严格超过**该日适用截止
        → 已逾期；等于截止仍算按时（技术方案 13.3）。
        """
        if task.canceled_at is not None:
            return "已取消"
        has_approved, has_pending = submission_flags
        if has_approved:
            return "已完成"
        if has_pending:
            return "待审核"
        if day is not None and utcnow() > day.deadline_at:
            return "已逾期"
        return "待执行"

    def _to_task_dto(
        self,
        task: InspectionTask,
        assignment: InspectionAssignment | None,
        day: SubmissionDeadlineDay | None,
        assessment: TaskDeadlineAssessment | None = None,
        deadline_version_id: int | None = None,
        submission_flags: tuple[bool, bool] = (False, False),
    ) -> InspectionTaskResponse:
        brief = (
            TaskAssignmentBrief(
                volunteer_user_id=assignment.volunteer_user_id,
                assign_method=assignment.assign_method,
            )
            if assignment is not None
            else None
        )
        assessment_brief = (
            DeadlineAssessmentBrief(
                result=assessment.result,
                deadline_at=assessment.deadline_at_snapshot,
                deadline_version_id=assessment.deadline_version_id,
                assignee_user_id=assessment.assignee_user_id_snapshot,
                evaluated_at=assessment.evaluated_at,
            )
            if assessment is not None
            else None
        )
        return InspectionTaskResponse(
            id=task.id,
            task_key=task.task_key,
            semester_id=task.semester_id,
            inspection_date=task.inspection_date,
            week_no=task.week_no,
            inspection_type=task.inspection_type,
            start_period=task.start_period,
            end_period=task.end_period,
            course_schedule_id=task.course_schedule_id,
            teaching_class_id=task.teaching_class_id,
            administrative_class_id=task.administrative_class_id,
            course_name_snapshot=task.course_name_snapshot,
            class_name_snapshot=task.class_name_snapshot,
            classroom_snapshot=task.classroom_snapshot,
            require_photo_snapshot=task.require_photo_snapshot,
            expected_count_snapshot=task.expected_count_snapshot,
            expected_count_current=task.expected_count_current,
            roster_version=task.roster_version,
            status=self._derive_status(task, assignment, day, submission_flags),
            assignment=brief,
            lock_version=task.lock_version,
            deadline_at=day.deadline_at if day is not None else None,
            deadline_version_id=deadline_version_id,
            deadline_assessment=assessment_brief,
        )

    # ---- 计划核心算法（预览与生成共用，均不在此锁学期；调用方负责锁定/只读确认）----
    def _build_course_plan_core(
        self, sem: Semester, body: InspectionGenerateRequest
    ) -> list[PlanItem]:
        tc_ids = [int(x) for x in (body.teaching_class_ids or [])]
        tcs = list(
            self._session.execute(
                select(TeachingClass).where(TeachingClass.id.in_(tc_ids))
            ).scalars().all()
        )
        found_ids = {t.id for t in tcs}
        missing = sorted(set(tc_ids) - found_ids)
        if missing:
            raise NotFoundError(f"以下教学班不存在：{missing}")
        for t in tcs:
            if t.semester_id != sem.id:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"教学班 {t.id} 不属于该学期",
                    http_status=422,
                    field_errors={"teaching_class_ids": tc_ids},
                )
        schedules = list(
            self._session.execute(
                select(CourseSchedule)
                .join(TeachingClass, TeachingClass.id == CourseSchedule.teaching_class_id)
                .join(Course, Course.id == TeachingClass.course_id).where(
                    CourseSchedule.teaching_class_id.in_(list(found_ids)),
                      CourseSchedule.semester_id == sem.id,
                    CourseSchedule.status == "ACTIVE",
                    TeachingClass.status == "ACTIVE",
                    Course.status == "ACTIVE",
                )
            ).scalars().all()
        )
        tc_course_ids = {t.course_id for t in tcs}
        course_name_by_id = (
            {
                c.id: c.course_name
                for c in self._session.execute(
                    select(Course).where(Course.id.in_(list(tc_course_ids)))
                ).scalars().all()
            }
            if tc_course_ids
            else {}
        )
        tc_course_name = {t.id: course_name_by_id.get(t.course_id) for t in tcs}
        tc_class_name = {t.id: t.class_name for t in tcs}
        # 候选页需要计算整个选择范围摘要；批量取名单，避免每个教学班一次查询。
        tc_roster: dict[int, list[Student]] = {t.id: [] for t in tcs}
        if found_ids:
            for tc_id, student in self._session.execute(
                select(TeachingClassStudent.teaching_class_id, Student)
                .join(Student, Student.id == TeachingClassStudent.student_id)
                .where(
                    TeachingClassStudent.teaching_class_id.in_(list(found_ids)),
                    Student.status == "ACTIVE",
                )
                .order_by(TeachingClassStudent.teaching_class_id, Student.id)
            ):
                tc_roster[tc_id].append(student)
        overrides = self._load_overrides(sem.id)
        items: dict[str, PlanItem] = {}
        for date_key, _week in self._resolve_dates(
            sem, body.week_nos, body.date_from, body.date_to
        ):
            teaching = resolve_teaching_day(sem.first_monday, date_key, overrides.get(date_key))
            if teaching is None:
                continue
            eff_week, eff_wd = teaching
            if eff_week < 1 or eff_week > sem.total_weeks:
                continue
            day_schedules = []
            for s in schedules:
                cname = tc_course_name.get(s.teaching_class_id)
                if is_course_exempt(cname, s.classroom):
                    continue
                if s.weekday != eff_wd:
                    continue
                if not any(w.week_no == eff_week for w in s.weeks):
                    continue
                day_schedules.append(s)

            groups: dict[tuple, list[CourseSchedule]] = {}
            for s in day_schedules:
                norm_room = re.sub(r"\s+", "", (s.classroom or "")).upper()
                cname = tc_course_name.get(s.teaching_class_id) or ""
                norm_course = re.sub(r"\s+", "", cname).upper()
                if norm_room:
                    grp_key = (s.start_period, s.end_period, norm_room, norm_course)
                else:
                    grp_key = (s.start_period, s.end_period, f"single:{s.id}", norm_course)
                groups.setdefault(grp_key, []).append(s)

            for grp_key, sched_list in groups.items():
                rep_s = min(sched_list, key=lambda x: x.id)
                c_sched_ids = sorted(x.id for x in sched_list)

                merged_students = []
                seen_sids = set()
                class_names_set = set()
                for sc in sched_list:
                    cl_name = tc_class_name.get(sc.teaching_class_id)
                    if cl_name:
                        class_names_set.add(cl_name)
                    for st in tc_roster.get(sc.teaching_class_id, []):
                        if st.id not in seen_sids:
                            seen_sids.add(st.id)
                            merged_students.append(st)

                class_names_list = sorted(class_names_set)
                if len(class_names_list) > 1:
                    merged_class_name = ", ".join(class_names_list) + " (合班)"
                elif class_names_list:
                    merged_class_name = class_names_list[0]
                else:
                    merged_class_name = tc_class_name.get(rep_s.teaching_class_id)

                if len(sched_list) > 1:
                    norm_room, norm_course = grp_key[2], grp_key[3]
                    target_hash = hashlib.md5(f"{norm_room}:{norm_course}".encode("utf-8")).hexdigest()[:10]
                    key = self._task_key(
                        sem.id, date_key, InspectionType.COURSE.value,
                        rep_s.start_period, rep_s.end_period, f"grp{target_hash}",
                    )
                else:
                    key = self._task_key(
                        sem.id, date_key, InspectionType.COURSE.value,
                        rep_s.start_period, rep_s.end_period, f"cs{rep_s.id}",
                    )

                if key in items:
                    continue

                items[key] = PlanItem(
                    task_key=key,
                    semester_id=sem.id,
                    inspection_date=date_key,
                    week_no=eff_week,
                    inspection_type=InspectionType.COURSE.value,
                    start_period=rep_s.start_period,
                    end_period=rep_s.end_period,
                    course_schedule_id=rep_s.id,
                    teaching_class_id=rep_s.teaching_class_id,
                    administrative_class_id=None,
                    course_name_snapshot=tc_course_name.get(rep_s.teaching_class_id),
                    class_name_snapshot=merged_class_name,
                    classroom_snapshot=rep_s.classroom,
                    require_photo_snapshot=body.require_photo,
                    student_ids=[st.id for st in merged_students],
                    constituent_schedule_ids=c_sched_ids,
                )
        return self._attach_rosters(list(items.values()))

    def _build_study_plan_core(
        self, sem: Semester, body: InspectionGenerateRequest
    ) -> list[PlanItem]:
        ac_ids = [int(x) for x in (body.administrative_class_ids or [])]
        acs = list(
            self._session.execute(
                select(AdministrativeClass).where(AdministrativeClass.id.in_(ac_ids))
            ).scalars().all()
        )
        found = {a.id: a for a in acs}
        missing = sorted(set(ac_ids) - set(found))
        if missing:
            raise NotFoundError(f"以下行政班不存在：{missing}")
        itype = body.inspection_type
        start_p = body.start_period or 1
        end_p = body.end_period or start_p
        ac_students: dict[int, list[Student]] = {}
        for a in found.values():
            ac_students[a.id] = list(
                self._session.execute(
                    select(Student).where(
                        Student.administrative_class_id == a.id,
                        Student.status == "ACTIVE",
                    ).order_by(Student.id)
                ).scalars().all()
            )
        overrides = self._load_overrides(sem.id)
        items: dict[str, PlanItem] = {}
        for date_key, week in self._resolve_dates(
            sem, body.week_nos, body.date_from, body.date_to
        ):
            ov = overrides.get(date_key)
            if ov is not None and ov.override_type == OverrideType.STOP.value:
                continue
            if week < 1 or week > sem.total_weeks:
                continue
            for a in found.values():
                key = self._task_key(sem.id, date_key, itype, start_p, end_p, f"ac{a.id}")
                if key in items:
                    continue
                students = ac_students.get(a.id, [])
                items[key] = PlanItem(
                    task_key=key,
                    semester_id=sem.id,
                    inspection_date=date_key,
                    week_no=week,
                    inspection_type=itype,
                    start_period=start_p,
                    end_period=end_p,
                    course_schedule_id=None,
                    teaching_class_id=None,
                    administrative_class_id=a.id,
                    course_name_snapshot=None,
                    class_name_snapshot=a.class_name,
                    classroom_snapshot=None,
                    require_photo_snapshot=body.require_photo,
                    student_ids=[st.id for st in students],
                )
        return self._attach_rosters(list(items.values()))

    # ================================================================== #
    # Wave 3a：排班（自动）与改派（人工）——硬约束 + volunteer_day_lock 并发
    # ================================================================== #
    # 硬约束（技术方案 11.2）：账号有效且为志愿者、本学期资格有效、避开本人行政班
    # 学生、与本人其他查课任务时段不冲突、与本人课表不冲突；软约束单日上限可配置。
    @staticmethod
    def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """大节次闭区间是否重叠（按完整起止范围比较，非仅起始节次）。"""
        return a_start <= b_end and b_start <= a_end

    def _load_volunteer(self, user_id: int) -> _VolProfile:
        """取候选志愿者的资格判定快照（状态 / VOLUNTEER 身份 / 绑定学生 / 行政班）。"""
        acct = self._session.scalar(
            select(UserAccount).where(UserAccount.id == user_id).with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if acct is None:
            return _VolProfile(user_id, "MISSING", False, None, None)
        is_vol = self._session.execute(
            select(UserRole.user_id).join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.code == RoleCode.VOLUNTEER.value)
            .with_for_update(read=True)
        ).first() is not None
        admin_class_id: int | None = None
        if acct.student_id is not None:
            stu = self._session.scalar(
                select(Student).where(Student.id == acct.student_id).with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if stu is not None and stu.status == "ACTIVE":
                admin_class_id = stu.administrative_class_id
            else:
                return _VolProfile(user_id, acct.status, is_vol, None, None)
        return _VolProfile(user_id, acct.status, is_vol, acct.student_id, admin_class_id)

    def _has_qualification(self, semester_id: int, student_id: int) -> bool:
        row = self._session.execute(
            select(VolunteerQualification.id)
            .where(
                VolunteerQualification.semester_id == semester_id,
                VolunteerQualification.student_id == student_id,
                VolunteerQualification.enabled.is_(True),
            )
            .limit(1).with_for_update(read=True)
        ).first()
        return row is not None

    def _roster_admin_class_ids(self, task: InspectionTask) -> set[int]:
        """任务当前名单成员所属行政班集合（本班回避判定用）。"""
        return set(self._session.scalars(
            select(Student.administrative_class_id)
            .join(TaskRosterMember, TaskRosterMember.student_id == Student.id)
            .where(TaskRosterMember.task_id == task.id,
                   TaskRosterMember.roster_version == task.roster_version,
                   Student.administrative_class_id.is_not(None))
            .with_for_update(read=True)
        ))

    def _own_class_conflict(
        self, student_id: int, sem: Semester, task: InspectionTask
    ) -> bool:
        """志愿者以学生身份的课表是否与任务时段冲突（真实起止节次区间重叠）。"""
        override = self._session.execute(
            select(CalendarOverride).where(CalendarOverride.semester_id == sem.id,
                                           CalendarOverride.date == task.inspection_date)
            .with_for_update(read=True).execution_options(populate_existing=True)
        ).scalar_one_or_none()
        teaching = resolve_teaching_day(sem.first_monday, task.inspection_date, override)
        if teaching is None:
            return False
        week, weekday = teaching
        if week < 1 or week > sem.total_weeks:
            return False
        q = (
            select(CourseSchedule.id)
            .join(
                TeachingClassStudent,
                TeachingClassStudent.teaching_class_id
                == CourseSchedule.teaching_class_id,
            )
            .join(CourseScheduleWeek, CourseScheduleWeek.schedule_id == CourseSchedule.id)
            .where(
                TeachingClassStudent.student_id == student_id,
                CourseSchedule.semester_id == sem.id,
                CourseSchedule.status == "ACTIVE",
                CourseSchedule.weekday == weekday,
                CourseScheduleWeek.week_no == week,
                CourseSchedule.start_period <= task.end_period,
                CourseSchedule.end_period >= task.start_period,
            )
            .limit(1).with_for_update(read=True)
        )
        return self._session.execute(q).first() is not None

    def _check_eligible(
        self,
        prof: _VolProfile,
        task: InspectionTask,
        sem: Semester,
        *,
        exclude_task_id: int,
        busy_slots: list[tuple[int, int]],
        busy_count: int,
        roster_acs: set[int],
        lock_conflicts: bool = False,
    ) -> tuple[str | None, str]:
        """返回 (冲突原因码, 说明)；通过则 (None, "")。同一判定供人工与自动共用。

        lock_conflicts=True 用于已持有 (志愿者, 日期) 锚点排他锁的临界区（人工改派与自动
        排班落库阶段），冲突扫描改用锁定读以看到并发方刚提交的受派，避免重叠时段双双通过。
        """
        if (task.inspection_type == InspectionType.COURSE.value
                and is_physical_education(task.course_name_snapshot)):
            return REASON_COURSE_NOT_INSPECTABLE, "体育课不作为被查目标"
        if prof.status != UserStatus.ACTIVE.value or not prof.is_volunteer:
            return REASON_NOT_VOLUNTEER, "账号非启用志愿者"
        if prof.student_id is None or not self._has_qualification(sem.id, prof.student_id):
            return REASON_NO_QUALIFICATION, "本学期无有效志愿者资格"
        if self._own_class_conflict(prof.student_id, sem, task):
            return REASON_OWN_CLASS, "与本人课表时段冲突"
        if prof.admin_class_id is not None and prof.admin_class_id in roster_acs:
            return REASON_SELF_CLASS, "被查名单含本人行政班学生"
        # 与本人其他受派查课任务时段冲突（排除当前任务本身）。
        db_rows = self._repo.list_assignments_for_volunteer_on_date(
            prof.user_id, task.inspection_date, for_update=lock_conflicts
        )
        for _a, other in db_rows:
            if other.id == exclude_task_id:
                continue
            if self._overlap(
                task.start_period, task.end_period, other.start_period, other.end_period
            ):
                return REASON_TASK_CONFLICT, "与本人其他查课任务时段重叠"
        for b_s, b_e in busy_slots:
            if self._overlap(task.start_period, task.end_period, b_s, b_e):
                return REASON_TASK_CONFLICT, "与本次批量排班内其他任务时段重叠"
        cap = get_settings().assignment_max_tasks_per_day
        if cap > 0:
            used = sum(1 for _a, other in db_rows if other.id != exclude_task_id)
            if used + busy_count + 1 > cap:
                return REASON_DAY_CAP, f"超出单日受派上限 {cap}"
        week_cap = get_settings().assignment_max_tasks_per_week
        if week_cap:
            monday = task.inspection_date - timedelta(days=task.inspection_date.weekday())
            query = (select(InspectionAssignment.id)
                     .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
                     .where(InspectionAssignment.volunteer_user_id == prof.user_id,
                            InspectionAssignment.revoked_at.is_(None),
                            InspectionTask.inspection_date >= monday,
                            InspectionTask.inspection_date < monday + timedelta(days=7),
                            InspectionTask.canceled_at.is_(None),
                            InspectionTask.id != exclude_task_id))
            if lock_conflicts:
                query = query.with_for_update(read=True)
            if len(self._session.execute(query).all()) >= week_cap:
                return "WEEK_CAP_EXCEEDED", f"超出每周受派上限 {week_cap}"
        return None, ""

    def _active_volunteer_user_ids(self, semester_id: int) -> list[int]:
        """全体有效候选志愿者：启用账号 + VOLUNTEER 角色 + 绑定学生 + 本学期有效资格。"""
        qual_students = select(VolunteerQualification.student_id).where(
            VolunteerQualification.semester_id == semester_id,
            VolunteerQualification.enabled.is_(True),
        )
        q = (
            select(UserAccount.id)
            .join(UserRole, UserRole.user_id == UserAccount.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserAccount.status == UserStatus.ACTIVE.value,
                Role.code == RoleCode.VOLUNTEER.value,
                UserAccount.student_id.is_not(None),
                UserAccount.student_id.in_(qual_students),
            )
            .distinct()
            .order_by(UserAccount.id)
        )
        return [int(r[0]) for r in self._session.execute(q).all()]

    def _lock_day_anchors(self, day_keys: set[tuple[int, date_]]) -> None:
        """按 (志愿者, 日期) 升序安全建立并锁定日期锚点（技术方案 15 全局锁层级顶层）。"""
        # 周上限启用时，人工和自动共用整周日期锚点，避免异日并发穿透周名额。
        if get_settings().assignment_max_tasks_per_week:
            day_keys = {(vid, dt - timedelta(days=dt.weekday()) + timedelta(days=i))
                        for vid, dt in day_keys for i in range(7)}
        for vid, dt in sorted(day_keys):
            self._repo.ensure_volunteer_day_lock(vid, dt)
        for vid, dt in sorted(day_keys):
            self._repo.lock_volunteer_day(vid, dt)

    @staticmethod
    def _assignment_snapshot(a: InspectionAssignment | None) -> dict | None:
        return (
            None
            if a is None
            else {"volunteer_user_id": a.volunteer_user_id, "assign_method": a.assign_method}
        )

    def _load_assign_targets(
        self, semester_id: int, body: AutoAssignRequest
    ) -> list[InspectionTask]:
        """范围内"未取消且尚未分配"的任务，供自动排班。"""
        stmt = (
            select(InspectionTask)
            .where(
                InspectionTask.semester_id == semester_id,
                InspectionTask.canceled_at.is_(None),
                InspectionTask.id.notin_(select(InspectionAssignment.task_id).where(
                    InspectionAssignment.revoked_at.is_(None)
                )),
            )
        )
        if body.task_ids:
            stmt = stmt.where(InspectionTask.id.in_([int(x) for x in body.task_ids]))
        elif body.inspection_date is not None:
            stmt = stmt.where(InspectionTask.inspection_date == body.inspection_date)
        elif body.date_from is not None and body.date_to is not None:
            stmt = stmt.where(
                InspectionTask.inspection_date >= body.date_from,
                InspectionTask.inspection_date <= body.date_to,
            )
        stmt = stmt.order_by(InspectionTask.inspection_date, InspectionTask.id).limit(501)
        return list(self._session.execute(stmt).scalars().all())

    # ---- 人工改派 ----
    def assign_manual(
        self,
        actor: CurrentUser,
        task_id: int,
        body: AssignmentSetRequest,
        request_id: str | None,
    ) -> InspectionTaskResponse:
        self._require(actor.id, perms.ASSIGN_PERMISSION)
        task = self._repo.get_task(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        sem = self._academic.get_semester_for_update(task.semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != SemesterStatus.ACTIVE.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "已归档学期不可排班")
        # 先读既有受派以决定需锁的日期锚点集合（原、新志愿者），再按顶层锁层级串行化。
        existing = self._repo.get_assignment_by_task(task_id)
        old_v = existing.volunteer_user_id if existing is not None else None
        day_keys: set[tuple[int, date_]] = {(body.volunteer_user_id, task.inspection_date)}
        if old_v is not None and old_v != body.volunteer_user_id:
            day_keys.add((old_v, task.inspection_date))
        self._lock_day_anchors(day_keys)
        # 日期锚点已持有，再锁任务行并复核状态 / 版本（技术方案 15）。
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可排班")
        if task.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化，请刷新后重试")
        prof = self._load_volunteer(body.volunteer_user_id)
        roster_acs = self._roster_admin_class_ids(task)
        code, msg = self._check_eligible(
            prof, task, sem, exclude_task_id=task.id, busy_slots=[], busy_count=0,
            roster_acs=roster_acs, lock_conflicts=True,
        )
        if code is not None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"排班校验未通过：{msg}",
                http_status=422,
                field_errors={"reason_code": code, "volunteer_user_id": body.volunteer_user_id},
            )
        existing = self._repo.get_assignment_by_task_for_update(task.id)
        before = self._assignment_snapshot(existing)
        if existing is None:
            existing = InspectionAssignment(
                task_id=task.id,
                volunteer_user_id=body.volunteer_user_id,
                assign_method=AssignMethod.MANUAL.value,
                assign_reason=body.reason,
                assigned_by=actor.id,
                lock_version=0,
            )
            self._repo.add(existing)
        else:
            existing.volunteer_user_id = body.volunteer_user_id
            existing.assign_method = AssignMethod.MANUAL.value
            existing.assign_reason = body.reason
            existing.assigned_by = actor.id
            existing.lock_version += 1
        task.lock_version += 1
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="assignment.manual_set",
            resource_type="inspection_assignment",
            resource_id=f"task:{task.id}",
            before=before,
            after={
                "volunteer_user_id": body.volunteer_user_id,
                "assign_method": AssignMethod.MANUAL.value,
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._assemble_tasks([task])[0]

    # ---- 自动排班（候选计划 + 提交前锁内重验，V1.0 请求内同步全成全败）----
    def auto_assign(
        self, actor: CurrentUser, body: AutoAssignRequest, request_id: str | None
    ) -> AutoAssignResultResponse:
        self._require(actor.id, perms.ASSIGN_PERMISSION)
        # 同学期自动请求串行；人工改派仍由共享日期锚点与任务锁保护。
        sem = self._academic.get_semester_for_update(body.semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        if sem.status != SemesterStatus.ACTIVE.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "已归档学期不可自动排班")
        # 鉴权可能已建立 RR 快照。学期锁到手后用独立连接建立新快照，
        # 且不向持有写锁的业务连接池再借一个连接：pool_size=1 时也不能自阻塞。
        bind = self._session.get_bind()
        source_engine = bind if isinstance(bind, Engine) else bind.engine
        reader_engine = create_engine(source_engine.url, poolclass=NullPool, pool_pre_ping=True)
        try:
            with Session(bind=reader_engine, autoflush=False) as reader:
                reader_service = InspectionService(reader)
                targets = reader_service._load_assign_targets(sem.id, body)
                if targets:
                    cand_ids = (
                        [int(x) for x in body.candidate_user_ids]
                        if body.candidate_user_ids
                        else reader_service._active_volunteer_user_ids(sem.id)
                    )
                    if len(targets) > 500 or len(set(cand_ids)) > 500:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "单次自动排班最多 500 个任务、500 名候选人",
                            http_status=422,
                        )
                    snapshot = load_snapshot(reader, sem, targets, cand_ids)
        finally:
            reader_engine.dispose()
        if not targets:
            return AutoAssignResultResponse(
                semester_id=sem.id, target_task_count=0, assigned_count=0,
                unassigned_count=0, assigned=[], unassigned=[],
            )
        result = plan_assignments(snapshot.tasks, snapshot.volunteers,
                                  day_cap=get_settings().assignment_max_tasks_per_day,
                                  week_cap=get_settings().assignment_max_tasks_per_week)
        task_by_id = {task.id: task for task in targets}
        plan = [(task_by_id[tid], vid) for tid, vid in result.assignments.items()]
        versions = {task.id: task.lock_version for task in targets}
        reject: dict[int, tuple[str, str]] = {}
        for tid, code in result.unassigned.items():
            code = snapshot.static_failures.get(tid, code)
            api_code = REASON_DAY_CAP if code == "DAY_CAP_EXCEEDED" else code
            reject[tid] = (api_code, REASONS[code])
        # Phase B：日期/周锚点 → 批量任务锁 → 输入当前锁定读 → 一次 flush。
        self._lock_day_anchors({(vid, t.inspection_date) for t, vid in plan})
        plan_ids = sorted(result.assignments)
        locked_tasks = list(self._session.scalars(
            select(InspectionTask).where(InspectionTask.id.in_(plan_ids))
            .order_by(InspectionTask.id).with_for_update()
            .execution_options(populate_existing=True)
        )) if plan_ids else []
        if len(locked_tasks) != len(plan_ids) or any(
            task.canceled_at is not None or task.lock_version != versions[task.id]
            for task in locked_tasks
        ):
            raise ConflictError(ErrorCode.ASSIGNMENT_CONFLICT, "任务已变化，请重新排班")
        taken = self._session.execute(
            select(InspectionAssignment.id).where(
                InspectionAssignment.task_id.in_(plan_ids),
                InspectionAssignment.revoked_at.is_(None),
            )
            .with_for_update()
        ).first() if plan_ids else None
        if taken is not None:
            raise ConflictError(ErrorCode.ASSIGNMENT_CONFLICT, "任务已被分配，请重新排班")
        if locked_tasks:
            current = load_snapshot(self._session, sem, locked_tasks,
                                    sorted(set(result.assignments.values())), lock_inputs=True)
            failure = validate_plan(current, result.assignments,
                                    day_cap=get_settings().assignment_max_tasks_per_day,
                                    week_cap=get_settings().assignment_max_tasks_per_week)
            if failure:
                raise ConflictError(ErrorCode.ASSIGNMENT_CONFLICT,
                                    f"排班输入已变化：{REASONS[failure[1]]}，请重试")
        assigned: list[PlannedAssignment] = []
        for locked in locked_tasks:
            vid = result.assignments[locked.id]
            self._repo.add(InspectionAssignment(
                task_id=locked.id, volunteer_user_id=vid,
                assign_method=AssignMethod.AUTO.value, assign_reason=body.reason,
                assigned_by=actor.id, lock_version=0,
            ))
            locked.lock_version += 1
            assigned.append(PlannedAssignment(task_id=locked.id, volunteer_user_id=vid))
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="assignment.auto_run",
            resource_type="inspection_assignment",
            resource_id=f"{sem.id}:batch",
            after={"target_task_count": len(targets), "assigned": len(assigned)},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        unassigned = [
            UnassignedTaskBrief(task_id=tid, reason_code=c, message=m)
            for tid, (c, m) in sorted(reject.items())
        ]
        return AutoAssignResultResponse(
            semester_id=sem.id,
            target_task_count=len(targets),
            assigned_count=len(assigned),
            unassigned_count=len(unassigned),
            assigned=assigned,
            unassigned=unassigned,
        )

    # ================================================================== #
    # Wave 3b：调班申请——志愿者对本人当前受派发起，管理人员读取与处理。
    # ================================================================== #
    # 语义边界：申请仅表达"本人希望调整该受派"的诉求并留痕，approve/reject 只迁移申请状态，
    # 不隐式改派——真正的改派仍走 assignment.manage（模型无替补志愿者字段，避免审核即换人的
    # 越权副作用）。数据范围：志愿者只读本人申请（强制 requester=本人）；管理视图读取全部。
    def create_change_request(
        self,
        actor: CurrentUser,
        body: ChangeRequestCreateRequest,
        request_id: str | None,
    ) -> ChangeRequestResponse:
        self._require(actor.id, perms.CHANGE_REQUEST_PERMISSION)
        assignment = self._repo.get_assignment(body.assignment_id)
        if assignment is None:
            raise NotFoundError("受派关系不存在")
        # "当前受派人"边界：非本人受派既不可代提申请。区分不存在(404)与越权(403)。
        if assignment.volunteer_user_id != actor.id:
            raise PermissionDeniedError("仅可对本人的当前受派发起调班申请")
        if assignment.revoked_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "受派已失效")
        task = self._repo.get_task(assignment.task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可发起调班申请")
        if self._repo.has_pending_change_request(assignment.id):
            raise ConflictError(
                ErrorCode.STATE_CONFLICT, "该受派已有待处理调班申请，请先等待处理"
            )
        req = AssignmentChangeRequest(
            assignment_id=assignment.id,
            request_user_id=actor.id,
            reason=body.reason,
            status=ChangeRequestStatus.PENDING.value,
        )
        self._repo.add(req)
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="assignment.change_request.create",
            resource_type="assignment_change_request",
            resource_id=f"{req.id}",
            after={"assignment_id": assignment.id, "status": ChangeRequestStatus.PENDING.value},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._to_change_request_dto(req, task.id)

    def list_my_change_requests(
        self, actor: CurrentUser, params: PageParams, *, status: str | None
    ) -> dict:
        # 志愿者读取本人申请：无论角色一律强制 requester=本人（PERMISSIONS.md 4.3）。
        self._require(actor.id, perms.CHANGE_REQUEST_PERMISSION)
        rows, total = self._repo.list_change_requests_with_task(
            params, status=status, requester_user_id=actor.id
        )
        return self._change_request_page(rows, total, params)

    def list_change_requests(
        self, actor: CurrentUser, params: PageParams, *, status: str | None
    ) -> dict:
        # 管理视图：assignment.change_review 读取全部申请（可按状态过滤）。
        self._require(actor.id, perms.CHANGE_REVIEW_PERMISSION)
        rows, total = self._repo.list_change_requests_with_task(
            params, status=status, requester_user_id=None
        )
        return self._change_request_page(rows, total, params)

    def review_change_request(
        self,
        actor: CurrentUser,
        request_id: int,
        body: ChangeRequestReviewRequest,
        request_id_str: str | None,
    ) -> ChangeRequestResponse:
        self._require(actor.id, perms.CHANGE_REVIEW_PERMISSION)
        req = self._repo.get_change_request_for_update(request_id)
        if req is None:
            raise NotFoundError("调班申请不存在")
        if req.status != ChangeRequestStatus.PENDING.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "该申请已处理，不可重复处理")
        assignment = self._repo.get_assignment(req.assignment_id)
        if assignment is None or assignment.revoked_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "受派已失效，不可处理旧调班申请")
        prev_status = req.status
        req.status = body.decision
        req.processed_by = actor.id
        req.processed_at = utcnow()
        req.comment = body.comment
        self._repo.flush()
        assignment = self._repo.get_assignment(req.assignment_id)
        task_id = assignment.task_id if assignment is not None else 0
        self._audit(
            actor_user_id=actor.id,
            action="assignment.change_request.review",
            resource_type="assignment_change_request",
            resource_id=f"{req.id}",
            before={"status": prev_status},
            after={"status": req.status, "comment": body.comment},
            reason=body.comment,
            request_id=request_id_str,
        )
        self._session.commit()
        return self._to_change_request_dto(req, task_id)

    @staticmethod
    def _to_change_request_dto(req: AssignmentChangeRequest, task_id: int) -> ChangeRequestResponse:
        return ChangeRequestResponse(
            id=req.id,
            assignment_id=req.assignment_id,
            task_id=task_id,
            request_user_id=req.request_user_id,
            reason=req.reason,
            status=req.status,
            processed_by=req.processed_by,
            processed_at=req.processed_at,
            comment=req.comment,
            created_at=req.created_at,
            updated_at=req.updated_at,
        )

    def _change_request_page(
        self,
        rows: Sequence[tuple[AssignmentChangeRequest, int]],
        total: int,
        params: PageParams,
    ) -> dict:
        return {
            "items": [self._to_change_request_dto(r, tid).model_dump() for r, tid in rows],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    # ================================================================== #
    # Wave 3c：取消 / 名单改版 / 截止时间配置 / 截止时考核快照结算
    # ================================================================== #

    # ---- 时间/偏移助手（冻结纪律：默认时刻与时区偏移均取自可配置 Settings）----
    def _deadline_offset(self) -> timedelta:
        return timedelta(hours=get_settings().app_utc_offset_hours)

    @staticmethod
    def _hhmm_to_parts(raw: str) -> tuple[int, int]:
        try:
            t = time.fromisoformat(raw.strip())
        except ValueError as exc:  # 非法 HH:MM → 422
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "截止时刻需为 HH:MM 格式",
                http_status=422,
                field_errors={"time": raw},
            ) from exc
        return t.hour, t.minute

    def _deadline_naive_utc(self, on_date: date_, hh: int, mm: int) -> datetime:
        # 本地墙上时钟组合后转 naive-UTC（与 utcnow()/已存 deadline_at 同域可比）。
        return datetime.combine(on_date, time(hh, mm)) - self._deadline_offset()

    # ---- 截止时考核快照：幂等结算（技术方案 13.3），须在持有任务行锁后调用 ----
    def _settle_assessment(
        self, task: InspectionTask, day: SubmissionDeadlineDay | None
    ) -> tuple[TaskDeadlineAssessment | None, str]:
        """回看截止时点结算既有事实，返回 (assessment, outcome)。

        outcome ∈ {"SETTLED", "SKIP", "NOT_DUE"}：

        - SKIP：已有快照——既成事实不被普通业务改写（幂等）；
        - NOT_DUE：未到期且未在截止前取消——不生成快照（deadlineAssessment 为 null）；
        - SETTLED：本次新建。

        结果判定：截止前已取消 → CANCELED；服务端时间严格超过适用截止（等值仍按时，
        技术方案 13.3）后回看提交历史——存在按时（submitted_at ≤ 截止）提交 → VALID_SUBMISSION，
        否则 → OVERDUE_UNEXECUTED。按时提交后被退回仍算截止时有效，不倒算为未执行。
        """
        # 存在性复查用锁定读（SELECT ... FOR UPDATE）：调用方已持任务行 FOR UPDATE 锁串行化，
        # 但 MySQL 默认 REPEATABLE READ 下本事务一致性读视图早在加锁前（_require /
        # list_unsettled_task_ids 的普通读）即定版，非锁定读会错过并发方刚提交的快照，
        # 使本应 SKIP 的落败方误入 INSERT 撞唯一约束而 500。锁定读绕过旧读视图读最新已提交，
        # 与排班冲突重查用 FOR SHARE 的原理一致（技术方案 15 / API_CONTRACT 全局锁层级）。
        existing = self._repo.get_assessment_for_update(task.id)
        if existing is not None:
            return existing, "SKIP"
        if day is None:
            return None, "NOT_DUE"
        now = utcnow()
        if task.canceled_at is not None and task.canceled_at <= day.deadline_at:
            result = DeadlineAssessmentResult.CANCELED
        elif now > day.deadline_at:
            if self._repo.has_on_time_submission(task.id, day.deadline_at):
                result = DeadlineAssessmentResult.VALID_SUBMISSION
            else:
                result = DeadlineAssessmentResult.OVERDUE_UNEXECUTED
        else:
            return None, "NOT_DUE"
        ver = self._repo.get_deadline_version(day.id, day.version)
        assignment = self._repo.get_assignment_by_task(task.id)
        asmt = TaskDeadlineAssessment(
            task_id=task.id,
            deadline_version_id=ver.id if ver is not None else None,
            deadline_at_snapshot=day.deadline_at,
            assignee_user_id_snapshot=(
                assignment.volunteer_user_id if assignment is not None else None
            ),
            result=result.value,
            evaluated_at=now,
        )
        self._repo.add(asmt)
        self._repo.flush()
        return asmt, "SETTLED"

    # ---- 有界同步结算：不依赖页面访问（技术方案 13.3、15）----
    def settle_deadline(
        self, actor: CurrentUser, body: DeadlineSettleRequest, request_id: str | None
    ) -> DeadlineSettleResultResponse:
        self._require(actor.id, perms.DEADLINE_MANAGE_PERMISSION)
        sem = self._academic.get_semester(body.semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        candidate_ids = self._repo.list_unsettled_task_ids(
            body.semester_id,
            inspection_date=body.inspection_date,
            task_ids=body.task_ids,
            limit=body.limit,
        )
        settled = already = not_due = 0
        results: list[SettledTaskBrief] = []
        for tid in candidate_ids:
            task = self._repo.get_task_for_update(tid)  # 锁任务行，收敛并发双结算
            if task is None:
                continue
            day = self._repo.get_deadline_day(task.semester_id, task.inspection_date)
            asmt, outcome = self._settle_assessment(task, day)
            if outcome == "NOT_DUE":
                not_due += 1
            elif outcome == "SKIP":
                already += 1
            elif asmt is not None:
                settled += 1
                results.append(SettledTaskBrief(task_id=tid, result=asmt.result))
        self._audit(
            actor_user_id=actor.id,
            action="submission_deadline.settle",
            resource_type="task_deadline_assessment",
            resource_id=f"{sem.id}:batch",
            after={
                "considered": len(candidate_ids),
                "settled": settled,
                "already_settled": already,
                "not_due": not_due,
            },
            reason=None,
            request_id=request_id,
        )
        self._session.commit()
        return DeadlineSettleResultResponse(
            semester_id=sem.id,
            considered=len(candidate_ids),
            settled=settled,
            already_settled=already,
            not_due=not_due,
            results=results,
        )

    # ---- 取消任务（inspection.cancel）：锁内先结算、再置取消（技术方案 9.2、13.3）----
    def cancel_task(
        self,
        actor: CurrentUser,
        task_id: int,
        body: TaskCancelRequest,
        request_id: str | None,
    ) -> InspectionTaskResponse:
        self._require(actor.id, perms.CANCEL_PERMISSION)
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可重复取消")
        if task.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化，请刷新后重试")
        # 已有审核通过提交（已生成考勤）者不可取消：考勤事实已成立，取消致不一致（技术方案 51）。
        if self._repo.has_approved_submission(task.id):
            raise ConflictError(
                ErrorCode.STATE_CONFLICT, "任务已有审核通过提交并生成考勤，不可取消"
            )
        # 取消前按当前适用截止版本幂等结算，锁定"截止时"事实不受本次取消影响。
        day = self._repo.get_deadline_day(task.semester_id, task.inspection_date)
        self._settle_assessment(task, day)
        prev_lock = task.lock_version
        task.canceled_at = utcnow()
        task.canceled_by = actor.id
        task.cancel_reason = body.reason
        task.lock_version += 1
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="inspection.task.cancel",
            resource_type="inspection_task",
            resource_id=f"{task.id}",
            before={"canceled_at": None, "lock_version": prev_lock},
            after={"canceled_by": actor.id, "lock_version": task.lock_version},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._assemble_tasks([task])[0]

    def update_task_schedule_info(
        self,
        actor: CurrentUser,
        task_id: int,
        body: InspectionTaskUpdateRequest,
        request_id: str | None,
    ) -> InspectionTaskResponse:
        self._require(actor.id, perms.GENERATE_PERMISSION)
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "已取消任务不可修改")
        if self._repo.has_approved_submission(task.id):
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已有审核通过提交并生成考勤，不可修改")

        before = {
            "classroom": task.classroom_snapshot,
            "start_period": task.start_period,
            "end_period": task.end_period,
            "course_name": task.course_name_snapshot,
            "lock_version": task.lock_version,
        }

        if body.classroom is not None:
            task.classroom_snapshot = body.classroom.strip() or None
        if body.course_name is not None:
            task.course_name_snapshot = body.course_name.strip() or None
        if body.start_period is not None:
            task.start_period = body.start_period
        if body.end_period is not None:
            task.end_period = body.end_period
        if task.end_period < task.start_period:
            raise AppError(ErrorCode.VALIDATION_ERROR, "结束节次不能小于起始节次", http_status=422)

        task.lock_version += 1
        self._repo.flush()

        after = {
            "classroom": task.classroom_snapshot,
            "start_period": task.start_period,
            "end_period": task.end_period,
            "course_name": task.course_name_snapshot,
            "lock_version": task.lock_version,
        }

        self._audit(
            actor_user_id=actor.id,
            action="inspection.task.update",
            resource_type="inspection_task",
            resource_id=f"{task.id}",
            before=before,
            after=after,
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._assemble_tasks([task])[0]

    # ---- 名单改版（inspection.roster.manage）：执行前更正，生成新版本并冻结快照 ----
    def create_roster_version(
        self,
        actor: CurrentUser,
        task_id: int,
        body: RosterVersionCreateRequest,
        request_id: str | None,
    ) -> InspectionTaskResponse:
        self._require(actor.id, perms.ROSTER_MANAGE_PERMISSION)
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可更正名单")
        if task.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化，请刷新后重试")
        if self._repo.has_open_submission(task.id):
            raise ConflictError(
                ErrorCode.STATE_CONFLICT, "任务已有待审或已通过提交，不可改版名单"
            )
        wanted = sorted({int(s) for s in body.student_ids})
        rows = self._session.execute(
            select(Student, AdministrativeClass)
            .outerjoin(
                AdministrativeClass,
                AdministrativeClass.id == Student.administrative_class_id,
            )
            .where(Student.id.in_(wanted))
        ).all() if wanted else []
        found: dict[int, Student] = {}
        snap: dict[int, tuple[Student, AdministrativeClass | None]] = {}
        for stu, ac in rows:
            found[stu.id] = stu
            snap[stu.id] = (stu, ac)
        missing = [s for s in wanted if s not in found]
        inactive = [s for s in wanted if s in found and found[s].status != "ACTIVE"]
        if missing or inactive:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "名单含不存在或非在读学生",
                http_status=422,
                field_errors={"missing_student_ids": missing, "inactive_student_ids": inactive},
            )
        new_version = task.roster_version + 1
        rv = TaskRosterVersion(
            task_id=task.id, version_no=new_version, reason=body.reason, created_by=actor.id
        )
        self._repo.add(rv)
        for sid in wanted:
            stu, ac = snap[sid]
            self._repo.add(
                TaskRosterMember(
                    task_id=task.id,
                    roster_version=new_version,
                    student_id=sid,
                    student_no=stu.student_no,
                    name=stu.name,
                    class_name_snapshot=ac.class_name if ac is not None else None,
                    grade_year_snapshot=ac.grade_year if ac is not None else None,
                )
            )
        prev_version = task.roster_version
        task.roster_version = new_version
        task.expected_count_current = len(wanted)
        task.lock_version += 1
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="inspection.roster.revise",
            resource_type="inspection_task",
            resource_id=f"{task.id}",
            before={"roster_version": prev_version},
            after={
                "roster_version": new_version,
                "expected_count_current": len(wanted),
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._assemble_tasks([task])[0]

    def list_roster_versions(
        self, actor: CurrentUser, task_id: int
    ) -> list[RosterVersionResponse]:
        self._require(actor.id, perms.ROSTER_READ_PERMISSION)
        scope = self._scope_filter(actor)
        task = self._repo.get_task_scoped(task_id, scope_filter=scope)
        if task is None:
            raise NotFoundError("查课任务不存在或不可见")
        out: list[RosterVersionResponse] = []
        for rv in self._repo.list_roster_versions(task.id):
            count = self._repo.count_roster_members(task.id, rv.version_no)
            out.append(
                RosterVersionResponse(
                    version_no=rv.version_no,
                    reason=rv.reason,
                    created_by=rv.created_by,
                    member_count=count,
                    created_at=rv.created_at,
                )
            )
        return out

    # ---- 截止时间配置（submission_deadline.read / manage）----
    def get_default_deadline(self, actor: CurrentUser) -> SubmissionDeadlineDefaultResponse:
        self._require(actor.id, perms.DEADLINE_READ_PERMISSION)
        settings = get_settings()
        return SubmissionDeadlineDefaultResponse(
            time=(settings.default_submission_deadline_time or "22:00").strip(),
            utc_offset_hours=settings.app_utc_offset_hours,
            description=(
                "全局默认提交截止时刻（本地墙上时钟 HH:MM），为新查课日首次建任务时播种所用；"
                "改此默认值属部署/配置动作，只影响后续新建日期记录，不追溯改写既有日截止。"
            ),
        )

    def _day_to_dto(self, day: SubmissionDeadlineDay) -> SubmissionDeadlineDayResponse:
        return SubmissionDeadlineDayResponse(
            semester_id=day.semester_id,
            inspection_date=day.inspection_date,
            deadline_at=day.deadline_at,
            version=day.version,
            updated_by=day.updated_by,
            reason=day.reason,
            task_count=self._repo.count_active_tasks_on_date(day.semester_id, day.inspection_date),
        )

    def list_deadline_days(
        self,
        actor: CurrentUser,
        *,
        semester_id: int,
        date_from: date_ | None,
        date_to: date_ | None,
    ) -> list[SubmissionDeadlineDayResponse]:
        self._require(actor.id, perms.DEADLINE_READ_PERMISSION)
        if self._academic.get_semester(semester_id) is None:
            raise NotFoundError("学期不存在")
        days = self._repo.list_deadline_days_by_semester(semester_id)
        picked = [
            d
            for d in days
            if (date_from is None or d.inspection_date >= date_from)
            and (date_to is None or d.inspection_date <= date_to)
        ]
        picked.sort(key=lambda d: d.inspection_date)
        return [self._day_to_dto(d) for d in picked]

    def get_deadline_day(
        self, actor: CurrentUser, semester_id: int, on_date: date_
    ) -> SubmissionDeadlineDayResponse:
        self._require(actor.id, perms.DEADLINE_READ_PERMISSION)
        day = self._repo.get_deadline_day(semester_id, on_date)
        if day is None:
            raise NotFoundError("该查课日尚无截止记录")
        return self._day_to_dto(day)

    def list_deadline_day_versions(
        self, actor: CurrentUser, semester_id: int, on_date: date_
    ) -> list[SubmissionDeadlineVersionResponse]:
        self._require(actor.id, perms.DEADLINE_READ_PERMISSION)
        day = self._repo.get_deadline_day(semester_id, on_date)
        if day is None:
            raise NotFoundError("该查课日尚无截止记录")
        return [
            SubmissionDeadlineVersionResponse(
                version_no=v.version_no,
                deadline_at=v.deadline_at,
                changed_by=v.changed_by,
                reason=v.reason,
                created_at=v.created_at,
            )
            for v in self._repo.list_deadline_versions(day.id)
        ]

    def _latest_task_end_naive_utc(
        self, semester: Semester, on_date: date_
    ) -> datetime | None:
        """当日未取消任务的最晚真实结束时刻（naive-UTC），据节次定义换算。

        缺节次时刻定义时保守返回 None（不阻断改期），仅在数据齐备时执行下界校验。
        """
        tasks = list(
            self._session.execute(
                select(InspectionTask).where(
                    InspectionTask.semester_id == semester.id,
                    InspectionTask.inspection_date == on_date,
                    InspectionTask.canceled_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        if not tasks:
            return None
        end_by_period = {
            pd.period_no: pd.end_time
            for pd in self._academic.list_period_definitions(semester.id)
            if pd.end_time is not None
        }
        latest: datetime | None = None
        for t in tasks:
            et = end_by_period.get(t.end_period)
            if et is None:
                continue
            naive = datetime.combine(on_date, et) - self._deadline_offset()
            if latest is None or naive > latest:
                latest = naive
        return latest

    def update_deadline_day(
        self,
        actor: CurrentUser,
        semester_id: int,
        on_date: date_,
        body: DeadlineDayUpdateRequest,
        request_id: str | None,
    ) -> SubmissionDeadlineDayResponse:
        self._require(actor.id, perms.DEADLINE_MANAGE_PERMISSION)
        sem = self._academic.get_semester(semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        day = self._repo.get_deadline_day_for_update(semester_id, on_date)
        if day is None:
            raise NotFoundError("该查课日尚无截止记录")
        if day.version != body.lock_version:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "该日截止版本已变化，请刷新后重试"
            )
        hh, mm = self._hhmm_to_parts(body.time)
        new_deadline = self._deadline_naive_utc(on_date, hh, mm)
        latest_end = self._latest_task_end_naive_utc(sem, on_date)
        if latest_end is not None and new_deadline < latest_end:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "截止时间不得早于当日最晚任务结束时刻",
                http_status=422,
                field_errors={
                    "reason_code": REASON_DEADLINE_EARLY,
                    "latest_task_end": latest_end.isoformat(),
                },
            )
        # 改期前按旧截止版本幂等结算该日未结算任务，锁定既有逾期事实（技术方案 13.1、13.3）。
        old_day_snapshot = day.deadline_at
        for tid in self._repo.list_unsettled_task_ids(
            semester_id, inspection_date=on_date, limit=5000
        ):
            t = self._repo.get_task_for_update(tid)
            if t is not None:
                self._settle_assessment(t, day)
        before = {"deadline_at": old_day_snapshot.isoformat(), "version": day.version}
        day.deadline_at = new_deadline
        day.version += 1
        day.updated_by = actor.id
        day.reason = body.reason
        self._repo.flush()
        self._repo.add(
            SubmissionDeadlineVersion(
                deadline_day_id=day.id,
                version_no=day.version,
                deadline_at=new_deadline,
                changed_by=actor.id,
                reason=body.reason,
            )
        )
        self._repo.flush()
        affected = self._repo.count_active_tasks_on_date(semester_id, on_date)
        self._audit(
            actor_user_id=actor.id,
            action="submission_deadline.day_update",
            resource_type="submission_deadline_day",
            resource_id=f"{semester_id}:{on_date.isoformat()}",
            before=before,
            after={
                "deadline_at": new_deadline.isoformat(),
                "version": day.version,
                "affected": affected,
            },
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._day_to_dto(day)

    # ================================================================== #
    # P5c：查课提交（submission.create / submission.read，OWN_SUBMISSION 范围）
    # ================================================================== #
    def _current_student_id(self, actor_user_id: int) -> int | None:
        acct = self._identity.get_user_by_id(actor_user_id)
        return acct.student_id if acct is not None else None

    def create_submission(
        self,
        actor: CurrentUser,
        task_id: int,
        body: SubmissionCreateRequest,
        request_id: str | None,
    ) -> SubmissionResponse:
        """志愿者对本人当前受派任务提交查课结果（技术方案 12、13.3、15）。

        身份三重实时校验（VOLUNTEER + 本学期资格 + 当前受派 + 未取消）与"至多一个待审核/
        审核通过提交"不变式，全在任务行锁内成立；补交前先幂等结算锁定截止时事实；
        提交时刻以服务端 UTC 记录，等于截止仍按时；迟交与适用截止版本一并冻结不被后续改写。
        """
        self._require(actor.id, perms.SUBMISSION_CREATE_PERMISSION)
        if actor.pre_binding:
            raise PermissionDeniedError("请先完成身份绑定")
        acct = self._identity.get_user_by_id(actor.id)
        if acct is None or acct.status != UserStatus.ACTIVE.value:
            raise PermissionDeniedError("账号已停用，不可提交")
        if RoleCode.VOLUNTEER.value not in set(self._identity.list_role_codes(actor.id)):
            raise PermissionDeniedError("仅志愿者可提交查课结果")

        # 任务行锁：串行化同任务的并发提交与结算（技术方案 15 全局锁层级）。
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可提交")

        # 当前受派：仅本人受派任务可提交；不存在受派或非本人 → 403（任务已确认存在 → 非 404）。
        assignment = self._repo.get_assignment_by_task(task.id)
        if assignment is None or assignment.volunteer_user_id != actor.id:
            raise PermissionDeniedError("仅可提交本人当前受派的任务")

        # 本学期有效志愿者资格：资格停用立即禁止提交（保留历史读取，见读取侧）。
        student_id = acct.student_id
        if student_id is None or not self._has_qualification(task.semester_id, student_id):
            raise PermissionDeniedError("本学期无有效志愿者资格，不可提交")

        # "至多一个待审核 / 审核通过提交"不变式：重复提交在锁内命中既有开放提交而拒；
        # 仅有被驳回历史提交时放行，生成下一 attempt（技术方案 12）。
        if self._repo.has_open_submission(task.id):
            raise ConflictError(
                ErrorCode.STATE_CONFLICT, "该任务已有待审核或审核通过提交，不可重复提交"
            )

        # 异常明细：学生须属本任务当前名单版本、不可重复；结论与明细数量一致性由 schema 保证。
        roster_members = self._repo.list_roster_members(task.id, task.roster_version)
        roster_ids = {m.student_id for m in roster_members}
        seen: set[int] = set()
        dup: list[int] = []
        not_in_roster: list[int] = []
        for item in body.abnormal_items:
            if item.student_id in seen:
                dup.append(item.student_id)
            seen.add(item.student_id)
            if item.student_id not in roster_ids:
                not_in_roster.append(item.student_id)
        if dup or not_in_roster:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "异常明细学生非法：重复或不属于本任务名单",
                http_status=422,
                field_errors={
                    "duplicate_student_ids": dup,
                    "not_in_roster_student_ids": not_in_roster,
                },
            )

        # 附件校验（技术方案 12、16.2）：照片要求、数量上限、归属、状态、有效期。
        file_ids = self._validate_attachments(task, actor.id, body.file_ids)

        # 补交前幂等结算：按旧截止版本锁定"截止时"事实不受本次提交影响（技术方案 13.3）。
        day = self._repo.get_deadline_day(task.semester_id, task.inspection_date)
        self._settle_assessment(task, day)

        now = utcnow()
        late = day is not None and now > day.deadline_at
        deadline_version_id: int | None = None
        if day is not None:
            ver = self._repo.get_deadline_version(day.id, day.version)
            deadline_version_id = ver.id if ver is not None else None

        attempt_no = self._repo.max_attempt_no(task.id) + 1
        sub = InspectionSubmission(
            task_id=task.id,
            attempt_no=attempt_no,
            volunteer_user_id=actor.id,
            roster_version=task.roster_version,
            result=body.result,
            review_status=ReviewStatus.PENDING.value,
            submitted_at=now,
            deadline_version_id=deadline_version_id,
            late_at_submission=late,
            note=body.note,
        )
        self._repo.add(sub)
        self._repo.flush()  # 取得 submission.id 供明细与附件外键
        for item in body.abnormal_items:
            self._repo.add(
                SubmissionAbnormalItem(
                    submission_id=sub.id,
                    student_id=item.student_id,
                    attendance_type=item.attendance_type,
                    note=item.note,
                )
            )
        for fid in file_ids:
            self._repo.add(SubmissionFile(submission_id=sub.id, file_id=fid))
        task.lock_version += 1
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action="submission.create",
            resource_type="inspection_submission",
            resource_id=f"{sub.id}",
            after={
                "task_id": task.id,
                "attempt_no": attempt_no,
                "result": body.result,
                "review_status": ReviewStatus.PENDING.value,
                "late_at_submission": late,
                "abnormal_count": len(body.abnormal_items),
                "file_count": len(file_ids),
                "submitted_at": now.isoformat(),
            },
            reason=body.note,
            request_id=request_id,
        )
        # 单一提交点：提交 + 异常明细 + 附件关联 + 结算快照 + 审计同事务原子生效。
        self._session.commit()
        self._session.refresh(sub)
        return self._assemble_submissions([sub])[0]

    def _validate_attachments(
        self, task: InspectionTask, actor_id: int, file_ids: list[int]
    ) -> list[int]:
        """校验并去重提交附件：均须 READY、本人上传、类别相符、未过期（技术方案 16.2）。"""
        settings = get_settings()
        uniq = list(dict.fromkeys(file_ids))
        if task.require_photo_snapshot and not uniq:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "本任务要求上传现场照片",
                http_status=422,
                field_errors={"file_ids": uniq},
            )
        cap = settings.file_max_files_per_submission
        if cap and len(uniq) > cap:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"单次提交附件不得超过 {cap} 个",
                http_status=422,
                field_errors={"file_ids": uniq},
            )
        bad: list[int] = []
        now = utcnow()
        for fid in uniq:
            f = self._session.get(FileObject, fid)
            if (
                f is None
                or f.status != FileStatus.READY.value
                or f.category != FileCategory.SUBMISSION_PHOTO.value
                or f.uploader_user_id != actor_id
                or (f.expires_at is not None and f.expires_at <= now)
            ):
                bad.append(fid)
        if bad:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "附件不存在、未就绪、非本人上传或已过期",
                http_status=422,
                field_errors={"file_ids": bad},
            )
        return uniq

    def list_my_submissions(
        self, actor: CurrentUser, params: PageParams, *, task_id: int | None
    ) -> dict:
        # 本人历史提交：无论角色一律强制 volunteer_user_id=本人（OWN_SUBMISSION，技术方案 12）。
        self._require(actor.id, perms.SUBMISSION_READ_PERMISSION)
        rows, total = self._repo.list_my_submissions(
            params, volunteer_user_id=actor.id, task_id=task_id
        )
        dto = self._assemble_submissions(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_my_submission(self, actor: CurrentUser, submission_id: int) -> SubmissionResponse:
        self._require(actor.id, perms.SUBMISSION_READ_PERMISSION)
        sub = self._repo.get_submission(submission_id)
        # 非本人或不存在统一 404，防枚举探测他人提交（PERMISSIONS.md 7）。
        if sub is None or sub.volunteer_user_id != actor.id:
            raise NotFoundError("提交不存在或不可见")
        return self._assemble_submissions([sub])[0]

    def _require_management_submission_read(self, actor: CurrentUser) -> None:
        self._require(actor.id, perms.SUBMISSION_REVIEW_PERMISSION)
        scope = perms.resolve_scope(self._identity.list_role_codes(actor.id))
        if not perms.is_management_scope(scope):
            raise PermissionDeniedError()

    def list_management_submissions(
        self,
        actor: CurrentUser,
        params: PageParams,
        *,
        semester_id: int | None,
        date_from: date_ | None,
        date_to: date_ | None,
        task_id: int | None,
        review_status: str | None,
    ) -> dict:
        self._require_management_submission_read(actor)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "date_from 不得晚于 date_to",
                http_status=422,
                field_errors={"date_from": "必须早于或等于 date_to"},
            )
        rows, total = self._repo.list_management_submissions(
            params,
            semester_id=semester_id,
            date_from=date_from,
            date_to=date_to,
            task_id=task_id,
            review_status=review_status,
        )
        dto = self._assemble_management_submissions(rows)
        return {
            "items": [d.model_dump() for d in dto],
            "page": params.page,
            "page_size": params.page_size,
            "total": total,
        }

    def get_management_submission(
        self, actor: CurrentUser, submission_id: int
    ) -> ManagementSubmissionResponse:
        self._require_management_submission_read(actor)
        sub = self._repo.get_submission(submission_id)
        if sub is None:
            raise NotFoundError("提交不存在或不可见")
        return self._assemble_management_submissions([sub])[0]

    def _assemble_management_submissions(
        self, subs: Sequence[InspectionSubmission]
    ) -> list[ManagementSubmissionResponse]:
        if not subs:
            return []
        base = self._assemble_submissions(subs)
        tasks = {t.id: t for t in self._repo.list_tasks_by_ids([s.task_id for s in subs])}
        result: list[ManagementSubmissionResponse] = []
        for sub, dto in zip(subs, base, strict=True):
            task = tasks[sub.task_id]
            result.append(
                ManagementSubmissionResponse(
                    **dto.model_dump(),
                    task=ManagementSubmissionTaskBrief(
                        id=str(task.id),
                        semester_id=str(task.semester_id),
                        inspection_date=task.inspection_date,
                        class_name_snapshot=task.class_name_snapshot,
                        course_name_snapshot=task.course_name_snapshot,
                        classroom_snapshot=task.classroom_snapshot,
                    ),
                )
            )
        return result

    # ---- 审核（submission.review）：通过据名单版本生成考勤，驳回保留原事实（技术方案 12、14）----
    def review_submission(
        self,
        actor: CurrentUser,
        submission_id: int,
        body: SubmissionReviewRequest,
        request_id: str | None,
    ) -> SubmissionResponse:
        """管理人员处理某待审核提交（技术方案 12、15）。

        锁序遵全局层级"任务→提交"：先无锁读定位所属任务，再锁任务、后锁提交并事务内重读，
        确保并发的审核 vs 取消、双人同审互斥（谁先持任务锁谁生效，落败方见既成事实得 409）。
        通过前按当前截止版本幂等结算锁定截止时事实；通过后为该名单版本每生建初始考勤
        （列异常者取明细类型，未列者 NORMAL），驳回仅改审核态、不动提交事实与照片。
        """
        self._require(actor.id, perms.SUBMISSION_REVIEW_PERMISSION)
        probe = self._repo.get_submission(submission_id)
        if probe is None:
            raise NotFoundError("提交不存在")
        task = self._repo.get_task_for_update(probe.task_id)
        if task is None:
            raise NotFoundError("提交所属任务不存在")
        sub = self._repo.get_submission_for_update(submission_id)
        if sub is None:
            raise NotFoundError("提交不存在")
        if sub.review_status != ReviewStatus.PENDING.value:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "提交已被处理，不可重复审核")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可审核提交")

        now = utcnow()
        generated = 0
        if body.decision == ReviewStatus.APPROVED.value:
            # 通过（生成考勤）前先幂等结算，锁定"截止时"事实不受本次审核影响（技术方案 13.3）。
            day = self._repo.get_deadline_day(task.semester_id, task.inspection_date)
            self._settle_assessment(task, day)
            generated = self._generate_attendance(sub, actor.id)
            sub.review_status = ReviewStatus.APPROVED.value
            # 考勤事实新增 → 同事务递增该(学期,周)报表源修订号（技术方案 9.4；W7b 还 P6 挂账）。
            SourceRevisionService.bump_for_task(self._session, task)
        else:
            sub.review_status = ReviewStatus.REJECTED.value
        sub.reviewed_by = actor.id
        sub.reviewed_at = now
        sub.review_comment = body.comment
        task.lock_version += 1
        self._repo.flush()
        self._audit(
            actor_user_id=actor.id,
            action=f"submission.review.{sub.review_status.lower()}",
            resource_type="inspection_submission",
            resource_id=f"{sub.id}",
            before={"review_status": ReviewStatus.PENDING.value},
            after={
                "review_status": sub.review_status,
                "attendance_generated": generated,
                "reviewed_at": now.isoformat(),
            },
            reason=body.comment,
            request_id=request_id,
        )
        self._session.commit()
        self._session.refresh(sub)
        return self._assemble_submissions([sub])[0]

    def _generate_attendance(self, sub: InspectionSubmission, actor_id: int) -> int:
        """审核通过时按提交所用名单版本为每生建初始考勤 + 版本 1（技术方案 12、14）。

        列异常者取该明细类型并回填 source_submission_item_id，未列者 NORMAL（明细引用为空）；
        一次批量插入并单次 flush 取得各行主键再补版本行，避免逐行往返。"至多一个审核通过
        提交"不变式保证同一任务考勤只生成一次，无需去重既有记录。返回生成的考勤条数。
        """
        abnormal = {i.student_id: i for i in sub.abnormal_items}
        members = self._repo.list_roster_members(sub.task_id, sub.roster_version)
        pending: list[tuple[AttendanceRecord, str, int | None]] = []
        for m in members:
            item = abnormal.get(m.student_id)
            eff = item.attendance_type if item is not None else AttendanceType.NORMAL.value
            item_id = item.id if item is not None else None
            rec = AttendanceRecord(
                task_id=sub.task_id,
                student_id=m.student_id,
                effective_type=eff,
                current_version=1,
                source_submission_item_id=item_id,
            )
            self._repo.add(rec)
            pending.append((rec, eff, item_id))
        self._repo.flush()  # 取得各 AttendanceRecord.id 供版本行外键
        for rec, eff, item_id in pending:
            self._repo.add(
                AttendanceRecordVersion(
                    attendance_record_id=rec.id,
                    version_no=1,
                    attendance_type=eff,
                    source_type=AttendanceSourceType.SUBMISSION.value,
                    source_id=item_id,
                    changed_by=actor_id,
                    reason=None,
                )
            )
        self._repo.flush()
        return len(pending)

    # ---- 应到人数调整（attendance.expected_count_adjust）：改当前值、留快照（技术方案 14）----
    def update_expected_count(
        self,
        actor: CurrentUser,
        task_id: int,
        body: ExpectedCountUpdateRequest,
        request_id: str | None,
    ) -> InspectionTaskResponse:
        """人工调整任务当前应到人数：非负、不得小于已认定异常数、乐观锁、不改名单与既有认定。"""
        self._require(actor.id, perms.EXPECTED_COUNT_ADJUST_PERMISSION)
        task = self._repo.get_task_for_update(task_id)
        if task is None:
            raise NotFoundError("查课任务不存在")
        if task.canceled_at is not None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "任务已取消，不可调整应到人数")
        if task.lock_version != body.lock_version:
            raise ConflictError(ErrorCode.VERSION_CONFLICT, "任务版本已变化，请刷新后重试")
        # 当前异常认定数（考勤非 NORMAL 者）= 人数下界，避免"应到 < 异常"不可能事实（技术方案 14）。
        abnormal_count = int(
            self._session.execute(
                select(func.count())
                .select_from(AttendanceRecord)
                .where(
                    AttendanceRecord.task_id == task.id,
                    AttendanceRecord.effective_type != AttendanceType.NORMAL.value,
                )
            ).scalar_one()
            or 0
        )
        if body.expected_count_current < abnormal_count:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"当前应到人数不得小于已认定的异常人数({abnormal_count})",
                http_status=422,
                field_errors={
                    "expected_count_current": body.expected_count_current,
                    "abnormal_count": abnormal_count,
                },
            )
        prev = task.expected_count_current
        task.expected_count_current = body.expected_count_current
        task.lock_version += 1
        self._repo.flush()
        # 应到人数是统计分母的一部分：真实变化才递增源修订号（无变化不算源变更）。
        if task.expected_count_current != prev:
            SourceRevisionService.bump_for_task(self._session, task)
        self._audit(
            actor_user_id=actor.id,
            action="attendance.expected_count_adjust",
            resource_type="inspection_task",
            resource_id=f"{task.id}",
            before={"expected_count_current": prev},
            after={"expected_count_current": task.expected_count_current},
            reason=body.reason,
            request_id=request_id,
        )
        self._session.commit()
        return self._assemble_tasks([task])[0]

    def _assemble_submissions(
        self, subs: Sequence[InspectionSubmission]
    ) -> list[SubmissionResponse]:
        """批量装配提交响应：异常明细回填名单快照学号/姓名，附件 id 一次聚合取（禁 N+1）。"""
        if not subs:
            return []
        sub_ids = [s.id for s in subs]
        files_map = self._repo.list_submission_file_ids_by_ids(sub_ids)
        roster_map = self._build_roster_display_map(subs)
        out: list[SubmissionResponse] = []
        for s in subs:
            display = roster_map.get((s.task_id, s.roster_version), {})
            items = [
                SubmissionAbnormalItemResponse(
                    student_id=i.student_id,
                    student_no=display.get(i.student_id, (None, None))[0],
                    name=display.get(i.student_id, (None, None))[1],
                    attendance_type=i.attendance_type,
                    note=i.note,
                )
                for i in s.abnormal_items
            ]
            out.append(
                SubmissionResponse(
                    id=s.id,
                    task_id=s.task_id,
                    attempt_no=s.attempt_no,
                    volunteer_user_id=s.volunteer_user_id,
                    roster_version=s.roster_version,
                    result=s.result,
                    review_status=s.review_status,
                    submitted_at=s.submitted_at,
                    deadline_version_id=s.deadline_version_id,
                    late_at_submission=s.late_at_submission,
                    note=s.note,
                    reviewed_by=s.reviewed_by,
                    reviewed_at=s.reviewed_at,
                    review_comment=s.review_comment,
                    abnormal_items=items,
                    file_ids=files_map.get(s.id, []),
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
            )
        return out

    def _build_roster_display_map(
        self, subs: Sequence[InspectionSubmission]
    ) -> dict[tuple[int, int], dict[int, tuple[str | None, str | None]]]:
        """为各提交所用名单版本建立 (task_id, version) -> {student_id: (学号, 姓名)} 显示映射。"""
        keys = {(s.task_id, s.roster_version) for s in subs}
        out: dict[tuple[int, int], dict[int, tuple[str | None, str | None]]] = {}
        for m in self._repo.list_submission_roster_members(keys):
            out.setdefault((m.task_id, m.roster_version), {})[m.student_id] = (
                m.student_no,
                m.name,
            )
        return out


__all__ = ["InspectionService", "PlanItem", "_VolProfile"]
