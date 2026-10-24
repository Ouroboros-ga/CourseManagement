"""Explicit weekly authorization and exact business-stage receipts; never auto-publish."""

from copy import deepcopy
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import iso_utc, utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import AdministrativeClass, Semester
from app.modules.audit.models import AuditLog
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
from app.modules.inspection.assignment_plan_service import AssignmentPlanService
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.weekly_models import WeeklyInspectionExecution, WeeklyInspectionPlan
from app.modules.inspection.weekly_schemas import WeeklyPlanUpdate, weekly_period
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.models import VolunteerGroup
from app.modules.volunteer.preparation_models import semester_group_config


class WeeklyInspectionService:
    def __init__(self, db, college_id, group_id, semester_id, *, environment=None):
        self.db, self.cid, self.gid, self.sid = db, college_id, group_id, semester_id
        self.environment = environment or get_settings().app_env

    def _enabled(self):
        settings = get_settings()
        if not (
            settings.agent_weekly_inspection_enabled
            and settings.campus_business_scoped_enabled
            and settings.campus_scheduling_enabled
            and self.environment == settings.app_env
        ):
            raise NotFoundError("每周排班尚未开放")

    def _context(self, actor, *, active=True):
        self._enabled()
        generate = resolve_scope(self.db, actor, self.cid, "inspection.generate", write=True)
        assign = resolve_scope(self.db, actor, self.cid, "assignment.manage", write=True)
        semester = self.db.scalar(
            select(Semester)
            .where(Semester.id == self.sid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        group = self.db.scalar(
            select(VolunteerGroup)
            .where(VolunteerGroup.id == self.gid, VolunteerGroup.college_id == self.cid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if semester is None or group is None:
            raise NotFoundError("学期或执行组不在当前范围")
        if active and (semester.status != "ACTIVE" or group.status != "ACTIVE"):
            raise ConflictError(message="学期或执行组已停用")
        return generate, assign, semester, group

    def _plan(self, *, lock=False):
        query = select(WeeklyInspectionPlan).where(
            WeeklyInspectionPlan.environment == self.environment,
            WeeklyInspectionPlan.college_id == self.cid,
            WeeklyInspectionPlan.group_id == self.gid,
            WeeklyInspectionPlan.semester_id == self.sid,
        )
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query.execution_options(populate_existing=True))

    def _authorizer(self, uid):
        repo = IdentityRepository(self.db)
        user = repo.get_user_by_id(uid)
        if user is None or user.status != "ACTIVE":
            raise PermissionDeniedError("计划负责人已停用")
        return CurrentUser(
            user.id,
            user.username,
            user.display_name,
            user.status,
            repo.list_effective_role_codes(uid),
            repo.list_effective_permissions(uid),
        )

    def _validate(self, actor, body):
        generate, assign, semester, group = self._context(actor)
        if body.last_week > semester.total_weeks:
            raise ConflictError(message="有效周次超过本学期")
        version = semester_group_config(self.db, group, semester.id)
        if version is None or not set(body.course_type_ids) <= set(
            version.configuration["course_type_ids"]
        ):
            raise NotFoundError("课程类型不在本执行组已发布范围")
        types = set(
            self.db.scalars(
                select(CourseType.id).where(
                    CourseType.id.in_(map(int, body.course_type_ids)),
                    CourseType.college_id == self.cid,
                    CourseType.status == "ACTIVE",
                )
            )
        )
        classes = set(
            self.db.scalars(
                select(AdministrativeClass.id).where(
                    AdministrativeClass.id.in_(map(int, body.counts)),
                    AdministrativeClass.college_id == self.cid,
                    AdministrativeClass.status == "ACTIVE",
                )
            )
        )
        if types != {int(v) for v in body.course_type_ids} or classes != {
            int(v) for v in body.counts
        }:
            raise NotFoundError("班级或课程类型不在本院有效范围")
        config = version.configuration
        if config["class_mode"] == "SPECIFIC" and not set(body.counts) <= set(config["class_ids"]):
            raise NotFoundError("班级不在本执行组范围")
        if any(
            not scope.permits_plan(self.gid, tid, set(), classes)
            for scope in (generate, assign)
            for tid in types
        ):
            raise PermissionDeniedError("周期计划的班级和类型范围超出当前授权")
        return semester, group, version

    @staticmethod
    def plan_dto(row):
        return {
            "id": str(row.id),
            "version": row.version,
            "enabled": row.enabled,
            "authorizer_user_id": str(row.authorizer_user_id),
            "college_id": str(row.college_id),
            "group_id": str(row.group_id),
            "semester_id": str(row.semester_id),
            **deepcopy(row.configuration),
        }

    @staticmethod
    def execution_dto(row):
        return {
            "id": str(row.id),
            "plan_id": str(row.plan_id),
            "plan_version": row.plan_version,
            "target_week": row.target_week,
            "due_at": iso_utc(row.due_at),
            "date_from": row.date_from.isoformat(),
            "date_to": row.date_to.isoformat(),
            "status": row.status,
            "reason_code": row.reason_code,
            "task_ids": list(row.task_ids),
            "assignment_plan_id": row.assignment_plan_id,
            "result": deepcopy(row.result_json),
            "publication_mode": "DRAFT_ONLY",
        }

    def _audit(self, actor_id, action, row_id, payload):
        self.db.add(
            AuditLog(
                actor_user_id=actor_id,
                action=f"inspection.weekly.{action}",
                resource_type="weekly_inspection",
                resource_id=str(row_id),
                after_json=payload,
            )
        )

    @atomic_write
    def save(self, actor, data):
        body = validated(WeeklyPlanUpdate, data)
        _, _, group_version = self._validate(actor, body)
        row = self._plan(lock=True)
        if body.current_version != (row.version if row else 0):
            raise ConflictError(message="每周计划已变化，请刷新后修改")
        if row is None:
            row = WeeklyInspectionPlan(
                environment=self.environment,
                college_id=self.cid,
                group_id=self.gid,
                semester_id=self.sid,
                version=0,
                created_at=utcnow(),
            )
            self.db.add(row)
        row.authorizer_user_id, row.group_config_id = actor.id, group_version.id
        row.version += 1
        row.enabled = body.enabled
        row.configuration = body.model_dump(mode="json", exclude={"current_version", "enabled"})
        self.db.flush()
        result = self.plan_dto(row)
        self._audit(actor.id, "policy", row.id, result)
        self.db.commit()
        return result

    @atomic_write
    def pause(self, actor, current_version):
        self._context(actor, active=False)
        row = self._plan(lock=True)
        if row is None:
            raise NotFoundError()
        if type(current_version) is not int or row.version != current_version:
            raise ConflictError(message="每周计划已变化，请刷新")
        row.enabled, row.version = False, row.version + 1
        result = self.plan_dto(row)
        self._audit(actor.id, "pause", row.id, result)
        self.db.commit()
        return result

    @atomic_write
    def register_due(self, plan_id, *, now=None):
        self._enabled()
        now = now or utcnow()
        initial = self._plan()
        if initial is None or initial.id != plan_id:
            raise NotFoundError()
        if not initial.enabled:
            self.db.rollback()
            return []
        expected_version, expected_owner = initial.version, initial.authorizer_user_id
        actor = self._authorizer(initial.authorizer_user_id)
        semester, _, version = self._validate(
            actor,
            WeeklyPlanUpdate.model_validate(
                {**initial.configuration, "current_version": initial.version, "enabled": True}
            ),
        )
        row = self._plan(lock=True)
        if (
            row.version != expected_version
            or row.authorizer_user_id != expected_owner
            or not row.enabled
            or row.group_config_id != version.id
        ):
            raise ConflictError(message="计划或执行组规则已变化，请负责人重新核对")
        existing = set(
            self.db.scalars(
                select(WeeklyInspectionExecution.target_week).where(
                    WeeklyInspectionExecution.plan_id == row.id
                )
            )
        )
        rows = []
        for week in range(row.configuration["first_week"], row.configuration["last_week"] + 1):
            due, start, end = weekly_period(semester, row.configuration, week)
            if datetime.combine(start, time.min) - timedelta(hours=8) <= row.created_at:
                continue
            if week in existing or now < due:
                continue
            missed = now >= datetime.combine(start, time.min) - timedelta(hours=8)
            run = WeeklyInspectionExecution(
                plan_id=row.id,
                plan_version=row.version,
                authorizer_user_id=row.authorizer_user_id,
                target_week=week,
                due_at=due,
                date_from=start,
                date_to=end,
                configuration={
                    "policy": deepcopy(row.configuration),
                    "group_config_id": row.group_config_id,
                },
                status="MISSED" if missed else "QUEUED",
                reason_code="WEEK_STARTED" if missed else None,
                task_ids=[],
            )
            self.db.add(run)
            rows.append(run)
        self.db.flush()
        result = [self.execution_dto(run) for run in rows]
        for run in rows:
            self._audit(
                actor.id,
                "due",
                run.id,
                {"plan_id": str(row.id), "target_week": run.target_week, "status": run.status},
            )
        self.db.commit()
        return result

    def _execution(self, eid, now):
        initial = self._plan()
        if initial is None:
            raise NotFoundError()
        expected_version, expected_owner = initial.version, initial.authorizer_user_id
        actor = self._authorizer(initial.authorizer_user_id)
        semester, _, group_version = self._validate(
            actor,
            WeeklyPlanUpdate.model_validate(
                {
                    **initial.configuration,
                    "current_version": initial.version,
                    "enabled": initial.enabled,
                }
            ),
        )
        plan = self._plan(lock=True)
        if plan.version != expected_version or plan.authorizer_user_id != expected_owner:
            raise ConflictError(message="计划在授权核对期间已变化，请重新读取执行记录")
        run = self.db.scalar(
            select(WeeklyInspectionExecution)
            .where(
                WeeklyInspectionExecution.id == eid, WeeklyInspectionExecution.plan_id == plan.id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise NotFoundError()
        if weekly_period(semester, run.configuration["policy"], run.target_week) != (
            run.due_at,
            run.date_from,
            run.date_to,
        ):
            raise ConflictError(message="校历教学周起点已变化，请重新核对本周执行")
        if (
            not plan.enabled
            or run.plan_version != plan.version
            or run.authorizer_user_id != plan.authorizer_user_id
            or run.configuration["group_config_id"] != group_version.id
        ):
            raise ConflictError(message="计划已暂停、修改或规则变化，原执行转人工核对")
        if (
            run.status == "MISSED"
            or now < run.due_at
            or now >= datetime.combine(run.date_from, time.min) - timedelta(hours=8)
        ):
            raise ConflictError(message="不在本周计划的生成窗口，不能补写过去课次")
        return actor, run

    @atomic_write
    def generate(self, execution_id, *, now=None):
        actor, run = self._execution(execution_id, now or utcnow())
        if run.status != "QUEUED":
            result = self.execution_dto(run)
            self.db.commit()
            return result
        config = run.configuration["policy"]
        body = {
            "semester_id": str(self.sid),
            "date_from": run.date_from.isoformat(),
            "date_to": run.date_to.isoformat(),
            "counts": config["counts"],
            "course_type_ids": config["course_type_ids"],
            "require_photo": config["require_photo"],
            "draw_id": f"weekly:{run.plan_id}:{run.target_week}",
        }
        sampling = GroupSamplingService(self.db, actor, self.cid, self.gid)
        preview = sampling.preview(body)
        generated = sampling.generate_in_transaction(body, preview["selection_revision"])
        run.task_ids = [item.task_id for item in generated.tasks]
        run.status = "GENERATED"
        run.result_json = generated.model_dump(mode="json")
        result = self.execution_dto(run)
        self._audit(
            actor.id, "generated", run.id, {"plan_id": str(run.plan_id), "task_ids": run.task_ids}
        )
        self.db.commit()
        return result

    @atomic_write
    def prepare(self, execution_id, *, now=None):
        actor, run = self._execution(execution_id, now or utcnow())
        if run.status == "PREPARED":
            draft = self._current_draft(run)
            if draft.status != "COMMITTED" and draft.expires_at <= utcnow():
                raise ConflictError(
                    message="草案已过期，请由管理员明确重新核对；原课次不会重复抽取"
                )
            result = self._draft_receipt(run, draft)
            self.db.commit()
            return result
        if run.status != "GENERATED" or not run.task_ids:
            raise ConflictError(message="请先完成本周期课次生成")
        draft = AssignmentPlanService(self.db, actor, self.cid, self.gid).preview_in_transaction(
            {
                "semester_id": str(self.sid),
                "task_ids": run.task_ids,
                "reason": f"每周计划{run.plan_id}第{run.target_week}周草案，需人工确认发布",
            }
        )
        run.assignment_plan_id, run.status = draft["id"], "PREPARED"
        run.result_json = draft
        result = self.execution_dto(run)
        self._audit(
            actor.id,
            "prepared",
            run.id,
            {
                "plan_id": str(run.plan_id),
                "assignment_plan_id": draft["id"],
                "assigned_count": len(draft["assigned"]),
                "unassigned_count": len(draft["unassigned"]),
            },
        )
        self.db.commit()
        return result

    def _current_draft(self, run):
        draft = self.db.scalar(
            select(AssignmentConfirmationPlan)
            .where(
                AssignmentConfirmationPlan.id == run.assignment_plan_id,
                AssignmentConfirmationPlan.college_id == self.cid,
                AssignmentConfirmationPlan.group_id == self.gid,
                AssignmentConfirmationPlan.semester_id == self.sid,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if draft is None or set(draft.payload["task_ids"]) != {int(v) for v in run.task_ids}:
            raise ConflictError(message="原草案与本周期任务不一致，请核对原记录")
        return draft

    def _draft_receipt(self, run, draft):
        return {
            **self.execution_dto(run),
            "assignment_plan_status": draft.status,
            **(
                {"publication_result": deepcopy(draft.result)}
                if draft.status == "COMMITTED"
                else {}
            ),
        }

    @atomic_write
    def refresh_draft(self, actor, execution_id):
        """Explicit human recheck, scoped to already-generated exact tasks; no new draw."""
        self._enabled()
        plans = AssignmentPlanService(self.db, actor, self.cid, self.gid)
        scope, _, _ = plans._context(self.sid)
        plan = self._plan(lock=True)
        if plan is None:
            raise NotFoundError()
        run = self.db.scalar(
            select(WeeklyInspectionExecution)
            .where(
                WeeklyInspectionExecution.id == execution_id,
                WeeklyInspectionExecution.plan_id == plan.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None or run.status not in {"GENERATED", "PREPARED"} or not run.task_ids:
            raise NotFoundError("本周期尚无可核对的任务")
        ids = {int(value) for value in run.task_ids}
        visible = set(
            self.db.scalars(
                select(InspectionTask.id).where(
                    InspectionTask.id.in_(ids),
                    InspectionTask.college_id == self.cid,
                    InspectionTask.group_id == self.gid,
                    InspectionTask.semester_id == self.sid,
                    scope.task_condition(),
                )
            )
        )
        if visible != ids:
            raise NotFoundError("本周期任务已超出当前授权范围")
        if run.assignment_plan_id:
            previous = self._current_draft(run)
            if previous.status == "COMMITTED":
                result = self._draft_receipt(run, previous)
                self.db.commit()
                return result
            previous.expires_at = min(previous.expires_at, utcnow())
        previous_id = run.assignment_plan_id
        draft = plans.preview_in_transaction(
            {
                "semester_id": str(self.sid),
                "task_ids": run.task_ids,
                "reason": f"人工重新核对每周计划{run.plan_id}第{run.target_week}周原任务",
            }
        )
        run.assignment_plan_id, run.status, run.result_json = draft["id"], "PREPARED", draft
        self._audit(
            actor.id,
            "rechecked",
            run.id,
            {
                "previous_assignment_plan_id": previous_id,
                "assignment_plan_id": draft["id"],
                "task_ids": run.task_ids,
            },
        )
        result = {**self.execution_dto(run), "assignment_plan_status": "READY"}
        self.db.commit()
        return result
