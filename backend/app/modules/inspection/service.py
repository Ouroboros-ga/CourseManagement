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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date as date_
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserRole, UserStatus
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.inspection import permissions as perms
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    AssignMethod,
    ChangeRequestStatus,
    DeadlineAssessmentResult,
    InspectionAssignment,
    InspectionTask,
    InspectionType,
    SubmissionDeadlineDay,
    SubmissionDeadlineVersion,
    TaskDeadlineAssessment,
    TaskRosterMember,
    TaskRosterVersion,
)
from app.modules.inspection.repository import InspectionRepository
from app.modules.inspection.schemas import (
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
    GeneratePreviewResponse,
    GenerateResultResponse,
    InspectionGenerateRequest,
    InspectionTaskResponse,
    PlannedAssignment,
    PlannedTaskBrief,
    RosterVersionCreateRequest,
    RosterVersionResponse,
    SettledTaskBrief,
    SubmissionDeadlineDayResponse,
    SubmissionDeadlineDefaultResponse,
    SubmissionDeadlineVersionResponse,
    TaskAssignmentBrief,
    TaskCancelRequest,
    TaskRosterMemberResponse,
    TaskRosterResponse,
    UnassignedTaskBrief,
)


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


def _makeup_week_of_date(first_monday: date_, on_date: date_) -> int:
    """调休补课日的"所在周"按其日历位置归入周次（用于取该周生效的课表）。"""
    return _week_no_for_date(first_monday, on_date)


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
        if actor is None:
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
                InspectionAssignment.volunteer_user_id == actor.id
            )
            return stmt.where(InspectionTask.id.in_(subq))
        scope = perms.resolve_scope(actor.roles)
        if perms.is_management_scope(scope):
            return None  # 管理范围：不加可见性谓词（V1.0 无学院分区）
        stmt = select(InspectionTask)
        subq = select(InspectionAssignment.task_id).where(
            InspectionAssignment.volunteer_user_id == actor.id
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
            if body.inspection_type == InspectionType.COURSE.value:
                items = self._build_course_plan_core(sem, body)
            else:
                items = self._build_study_plan_core(sem, body)
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
        # 单一提交点：任务 + 名单快照 + 截止记录 + 审计同事务原子生效。
        self._session.commit()
        return GenerateResultResponse(
            semester_id=sem.id,
            inspection_type=body.inspection_type,
            created=len(new_items),
            existed=len(existing),
            total_planned=len(items),
            deadline_days_seeded=seeded,
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
            result.append(self._to_task_dto(t, assignments.get(t.id), day, assessment, version_id))
        return result

    @staticmethod
    def _derive_status(
        task: InspectionTask,
        assignment: InspectionAssignment | None,  # noqa: ARG004 - 保留签名，P5 提交域据此精判
        day: SubmissionDeadlineDay | None,
    ) -> str:
        """五种当前状态派生（技术方案 12、13.3）。

        优先级：已取消 →（P5）已完成 →（P5）待审核 → 已逾期 → 待执行。

        Wave 3c 落地"截止时刻"这一维度：无有效提交（提交域属 P5，此刻恒成立）且服务端
        时间**严格超过**该日适用截止 → 已逾期；等于截止仍算按时（技术方案 13.3）。
        "已完成 / 待审核"依赖提交与审核事实，随 P5 submission 模块落地，此处以注释占位。
        """
        if task.canceled_at is not None:
            return "已取消"
        # P5：有审核通过提交 → 已完成；有待审核提交 → 待审核。
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
            status=self._derive_status(task, assignment, day),
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
                select(CourseSchedule).where(
                    CourseSchedule.teaching_class_id.in_(list(found_ids)),
                    CourseSchedule.status == "ACTIVE",
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
        tc_roster: dict[int, list[Student]] = {
            t.id: self._academic.get_roster_students(t.id) for t in tcs
        }
        overrides = self._load_overrides(sem.id)
        items: dict[str, PlanItem] = {}
        for date_key, week in self._resolve_dates(
            sem, body.week_nos, body.date_from, body.date_to
        ):
            ov = overrides.get(date_key)
            if ov is not None and ov.override_type == OverrideType.STOP.value:
                continue
            if ov is not None and ov.override_type == OverrideType.MAKEUP.value:
                eff_wd = ov.source_teaching_weekday
                eff_week = _makeup_week_of_date(sem.first_monday, date_key)
                if eff_wd is None:
                    continue
            else:
                eff_wd = date_key.isoweekday()
                eff_week = week
            if eff_week < 1 or eff_week > sem.total_weeks:
                continue
            for s in schedules:
                if s.weekday != eff_wd:
                    continue
                if not any(w.week_no == eff_week for w in s.weeks):
                    continue
                key = self._task_key(
                    sem.id, date_key, InspectionType.COURSE.value,
                    s.start_period, s.end_period, f"cs{s.id}",
                )
                if key in items:
                    continue
                students = tc_roster.get(s.teaching_class_id, [])
                items[key] = PlanItem(
                    task_key=key,
                    semester_id=sem.id,
                    inspection_date=date_key,
                    week_no=eff_week,
                    inspection_type=InspectionType.COURSE.value,
                    start_period=s.start_period,
                    end_period=s.end_period,
                    course_schedule_id=s.id,
                    teaching_class_id=s.teaching_class_id,
                    administrative_class_id=None,
                    course_name_snapshot=tc_course_name.get(s.teaching_class_id),
                    class_name_snapshot=tc_class_name.get(s.teaching_class_id),
                    classroom_snapshot=s.classroom,
                    require_photo_snapshot=body.require_photo,
                    student_ids=[st.id for st in students],
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
        acct = self._identity.get_user_by_id(user_id)
        if acct is None:
            return _VolProfile(user_id, "MISSING", False, None, None)
        is_vol = RoleCode.VOLUNTEER.value in set(self._identity.list_role_codes(user_id))
        admin_class_id: int | None = None
        if acct.student_id is not None:
            stu = self._academic.get_student(acct.student_id)
            if stu is not None:
                admin_class_id = stu.administrative_class_id
        return _VolProfile(user_id, acct.status, is_vol, acct.student_id, admin_class_id)

    def _has_qualification(self, semester_id: int, student_id: int) -> bool:
        row = self._session.execute(
            select(VolunteerQualification.id)
            .where(
                VolunteerQualification.semester_id == semester_id,
                VolunteerQualification.student_id == student_id,
                VolunteerQualification.enabled.is_(True),
            )
            .limit(1)
        ).first()
        return row is not None

    def _roster_admin_class_ids(self, task: InspectionTask) -> set[int]:
        """任务当前名单成员所属行政班集合（本班回避判定用）。"""
        members = self._repo.list_roster_members(task.id, task.roster_version)
        sids = [m.student_id for m in members]
        if not sids:
            return set()
        rows = self._session.execute(
            select(Student.administrative_class_id).where(Student.id.in_(sids))
        ).all()
        return {r[0] for r in rows if r[0] is not None}

    def _own_class_conflict(
        self, student_id: int, sem: Semester, task: InspectionTask
    ) -> bool:
        """志愿者以学生身份的课表是否与任务时段冲突（真实起止节次区间重叠）。"""
        weekday = task.inspection_date.isoweekday()
        week = _week_no_for_date(sem.first_monday, task.inspection_date)
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
            .limit(1)
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
                InspectionTask.id.notin_(select(InspectionAssignment.task_id)),
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
        stmt = stmt.order_by(InspectionTask.inspection_date, InspectionTask.id)
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
        sem = self._academic.get_semester(task.semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
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
        sem = self._academic.get_semester(body.semester_id)
        if sem is None:
            raise NotFoundError("学期不存在")
        targets = self._load_assign_targets(sem.id, body)
        if not targets:
            return AutoAssignResultResponse(
                semester_id=sem.id, target_task_count=0, assigned_count=0,
                unassigned_count=0, assigned=[], unassigned=[],
            )
        cand_ids = (
            [int(x) for x in body.candidate_user_ids]
            if body.candidate_user_ids
            else self._active_volunteer_user_ids(sem.id)
        )
        profiles = {uid: self._load_volunteer(uid) for uid in cand_ids}
        cand_sorted = sorted(profiles)
        tasks_sorted = sorted(targets, key=lambda t: (t.inspection_date, t.id))
        # Phase A：无锁贪心生成候选计划，批内占用以 busy 记录（避免同日自我冲突）。
        busy_slots: dict[tuple[int, date_], list[tuple[int, int]]] = {}
        busy_count: dict[tuple[int, date_], int] = {}
        plan: list[tuple[InspectionTask, int]] = []
        reject: dict[int, tuple[str, str]] = {}
        for task in tasks_sorted:
            roster_acs = self._roster_admin_class_ids(task)
            chosen: int | None = None
            first_code: str | None = None
            first_msg = ""
            for vid in cand_sorted:
                key = (vid, task.inspection_date)
                code, msg = self._check_eligible(
                    profiles[vid], task, sem, exclude_task_id=task.id,
                    busy_slots=busy_slots.get(key, []), busy_count=busy_count.get(key, 0),
                    roster_acs=roster_acs,
                )
                if code is None:
                    chosen = vid
                    break
                if first_code is None:
                    first_code, first_msg = code, msg
            if chosen is None:
                reject[task.id] = (
                    first_code or REASON_NO_QUALIFICATION,
                    first_msg or "无合格志愿者",
                )
                continue
            plan.append((task, chosen))
            key = (chosen, task.inspection_date)
            busy_slots.setdefault(key, []).append((task.start_period, task.end_period))
            busy_count[key] = busy_count.get(key, 0) + 1
        # Phase B：单事务内按全局锁层级（日期锚点 → 任务升序）加锁并逐条重验后落库。
        self._lock_day_anchors({(vid, t.inspection_date) for t, vid in plan})
        plan_sorted = sorted(plan, key=lambda tv: tv[0].id)
        for t, _vid in plan_sorted:
            self._repo.get_task_for_update(t.id)  # 先按 id 升序取得全部任务行锁
        assigned: list[PlannedAssignment] = []
        for t, vid in plan_sorted:
            locked = self._repo.get_task_for_update(t.id)
            if locked is None:
                continue
            if locked.canceled_at is not None:
                reject[locked.id] = (REASON_NOT_VOLUNTEER, "任务已取消")
                continue
            if self._repo.get_assignment_by_task(locked.id) is not None:
                reject[locked.id] = (REASON_TASK_CONFLICT, "任务已被并发分配")
                continue
            prof = self._load_volunteer(vid)
            roster_acs = self._roster_admin_class_ids(locked)
            code, msg = self._check_eligible(
                prof, locked, sem, exclude_task_id=locked.id, busy_slots=[], busy_count=0,
                roster_acs=roster_acs, lock_conflicts=True,
            )
            if code is not None:
                reject[locked.id] = (code, msg)
                continue
            self._repo.add(
                InspectionAssignment(
                    task_id=locked.id,
                    volunteer_user_id=vid,
                    assign_method=AssignMethod.AUTO.value,
                    assign_reason=body.reason,
                    assigned_by=actor.id,
                    lock_version=0,
                )
            )
            locked.lock_version += 1
            self._repo.flush()
            assigned.append(PlannedAssignment(task_id=locked.id, volunteer_user_id=vid))
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

        结果判定（提交域属 P5，当前恒"无有效提交"）：截止前已取消 → CANCELED；
        服务端时间严格超过适用截止（等值仍按时，技术方案 13.3）→ OVERDUE_UNEXECUTED。
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


__all__ = ["InspectionService", "PlanItem", "_VolProfile"]
