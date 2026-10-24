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
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.weekly_models import WeeklyInspectionExecution, WeeklyInspectionPlan
from app.modules.inspection.weekly_schemas import WeeklyPlanUpdate, weekly_period
from app.modules.organization.service import atomic_write, validated
from app.modules.volunteer.models import VolunteerGroup
from app.modules.volunteer.preparation_models import semester_group_config


def configuration_permitted(scopes, group_id, configuration):
    classes = {int(v) for v in configuration["counts"]}
    types = {int(v) for v in configuration["course_type_ids"]}
    return bool(classes and types) and all(
        scope.permits_plan(group_id, tid, set(), classes)
        for scope in scopes for tid in types
    )


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
        if row is not None and not configuration_permitted(
            [resolve_scope(self.db, actor, self.cid, action, write=True)
             for action in ("inspection.generate", "assignment.manage")],
            self.gid, row.configuration,
        ):
            raise NotFoundError("原每周计划超出当前授权范围")
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
        generate, assign, _, _ = self._context(actor, active=False)
        row = self._plan(lock=True)
        if row is None or not configuration_permitted(
            (generate, assign), self.gid, row.configuration,
        ):
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
            if run.assignment_plan_id is None:
                plans = AssignmentPlanService(self.db, actor, self.cid, self.gid)
                coverage = self._partition(plans, run)
                if (
                    (run.result_json or {}).get("kind") != "ALREADY_ASSIGNED"
                    or coverage != self._saved_coverage(run)
                    or coverage["draft_task_ids"]
                ):
                    raise ConflictError(message="原受派记录已变化，请由管理员重新核对")
                result = self.execution_dto(run)
                self.db.commit()
                return result
            draft = self._current_draft(run)
            if draft.status != "COMMITTED" and draft.expires_at <= utcnow():
                raise ConflictError(
                    message="草案已过期，请由管理员明确重新核对；原课次不会重复抽取"
                )
            result = self._draft_receipt(actor, run, draft)
            self.db.commit()
            return result
        if run.status != "GENERATED" or not run.task_ids:
            raise ConflictError(message="请先完成本周期课次生成")
        self._prepare_remaining(
            AssignmentPlanService(self.db, actor, self.cid, self.gid), run,
            f"每周计划{run.plan_id}第{run.target_week}周草案，需人工确认发布",
        )
        result = self.execution_dto(run)
        self._audit(
            actor.id,
            "prepared",
            run.id,
            {
                "plan_id": str(run.plan_id),
                "assignment_plan_id": run.assignment_plan_id,
                "coverage": run.result_json["coverage"],
                "assigned_count": len(run.result_json["assigned"]),
                "unassigned_count": len(run.result_json["unassigned"]),
            },
        )
        self.db.commit()
        return result

    def _partition(self, plans, run):
        """Lock the exact original sample before observing active assignment facts."""
        plans._context(self.sid)
        tasks = plans._targets(self.sid, [int(v) for v in run.task_ids], lock=True)
        assigned = list(self.db.scalars(
            select(InspectionAssignment)
            .where(
                InspectionAssignment.task_id.in_([task.id for task in tasks]),
                InspectionAssignment.revoked_at.is_(None),
            )
            .order_by(InspectionAssignment.task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ))
        covered = {row.task_id for row in assigned}
        return {
            "sampled_task_ids": list(run.task_ids),
            "draft_task_ids": [tid for tid in run.task_ids if int(tid) not in covered],
            "already_assigned": [
                {"task_id": str(row.task_id), "assignment_id": str(row.id)} for row in assigned
            ],
        }

    @staticmethod
    def _saved_coverage(run):
        coverage = (run.result_json or {}).get("coverage")
        if coverage is None:
            # Drafts created before coverage partitioning targeted the entire sample.
            return {
                "sampled_task_ids": list(run.task_ids),
                "draft_task_ids": list(run.task_ids), "already_assigned": [],
            }
        ids = list(run.task_ids)
        try:
            targets = coverage["draft_task_ids"]
            skipped = [item["task_id"] for item in coverage["already_assigned"]]
            valid = (
                coverage["sampled_task_ids"] == ids
                and len(set(ids)) == len(ids)
                and len(set(targets)) == len(targets)
                and len(set(skipped)) == len(skipped)
                and not set(targets) & set(skipped)
                and set(targets) | set(skipped) == set(ids)
                and all(type(v) is str and v.isdecimal() for v in targets + skipped)
                and all(
                    type(item["assignment_id"]) is str and item["assignment_id"].isdecimal()
                    for item in coverage["already_assigned"]
                )
            )
        except (KeyError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ConflictError(message="原草案覆盖记录与本周期任务不一致，请核对原记录")
        return coverage

    def _prepare_remaining(self, plans, run, reason):
        coverage = self._partition(plans, run)
        if coverage["draft_task_ids"]:
            draft = plans.preview_in_transaction({
                "semester_id": str(self.sid), "task_ids": coverage["draft_task_ids"],
                "reason": reason,
            })
            run.assignment_plan_id, run.reason_code = draft["id"], None
        else:
            draft = {"kind": "ALREADY_ASSIGNED", "assigned": [], "unassigned": []}
            run.assignment_plan_id, run.reason_code = None, "ALL_TASKS_ASSIGNED"
        run.status, run.result_json = "PREPARED", {**draft, "coverage": coverage}

    def _current_draft(self, run):
        coverage = self._saved_coverage(run)
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
        if (
            draft is None or not coverage["draft_task_ids"]
            or set(draft.payload["task_ids"]) != {int(v) for v in coverage["draft_task_ids"]}
        ):
            raise ConflictError(message="原草案与本周期任务不一致，请核对原记录")
        return draft

    def _draft_receipt(self, actor, run, draft):
        coverage = self._saved_coverage(run)
        plans = AssignmentPlanService(self.db, actor, self.cid, self.gid)
        scope, _, _ = plans._context(self.sid)
        ids = {int(v) for v in run.task_ids}
        visible = set(self.db.scalars(
            select(InspectionTask.id).where(
                InspectionTask.id.in_(ids), InspectionTask.college_id == self.cid,
                InspectionTask.group_id == self.gid, InspectionTask.semester_id == self.sid,
                scope.task_condition(),
            ).order_by(InspectionTask.id).with_for_update()
        ))
        if visible != ids:
            raise NotFoundError("本周期任务已超出当前授权范围")
        skipped = coverage["already_assigned"]
        current = {
            str(row.task_id): str(row.id)
            for row in self.db.scalars(
                select(InspectionAssignment).where(
                    InspectionAssignment.task_id.in_([int(item["task_id"]) for item in skipped]),
                    InspectionAssignment.revoked_at.is_(None),
                ).order_by(InspectionAssignment.task_id).with_for_update()
                .execution_options(populate_existing=True)
            )
        }
        changes = [
            {"task_id": item["task_id"], "expected_assignment_id": item["assignment_id"],
             "current_assignment_id": current.get(item["task_id"])}
            for item in skipped if current.get(item["task_id"]) != item["assignment_id"]
        ]
        if changes and draft.status != "COMMITTED":
            raise ConflictError(message="原受派记录已变化，请由管理员重新核对")
        return {
            **self.execution_dto(run),
            "assignment_plan_status": draft.status,
            "coverage_status": "CHANGED" if changes else "CURRENT",
            "coverage_changes": changes,
            "requires_manual_recheck": bool(changes),
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
                result = self._draft_receipt(actor, run, previous)
                self.db.commit()
                return result
            previous.expires_at = min(previous.expires_at, utcnow())
        previous_id = run.assignment_plan_id
        self._prepare_remaining(
            plans, run, f"人工重新核对每周计划{run.plan_id}第{run.target_week}周原任务",
        )
        self._audit(
            actor.id,
            "rechecked",
            run.id,
            {
                "previous_assignment_plan_id": previous_id,
                "assignment_plan_id": run.assignment_plan_id,
                "task_ids": run.task_ids,
                "coverage": run.result_json["coverage"],
            },
        )
        result = self.execution_dto(run)
        if run.assignment_plan_id:
            result["assignment_plan_status"] = "READY"
        self.db.commit()
        return result
