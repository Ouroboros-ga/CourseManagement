"""One execution-group boundary for generic/manual occurrence generation."""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import CourseSchedule, TeachingClass
from app.modules.identity.resource_scope import resolve_scope
from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup
from app.modules.volunteer.policy import InspectionScope


def prepare(service, actor, body):
    service._generation_group = None
    service._generation_scope = None
    if not get_settings().campus_scheduling_enabled:
        return
    if body.inspection_type != "COURSE" or not body.execution_group_id:
        raise ConflictError(message="组织模式生成须选择执行组；早晚自习请使用统一正式课程")
    if not 0 < int(body.execution_group_id) < 2**63:
        raise ConflictError(message="执行组标识超出范围")
    group = service._session.get(
        VolunteerGroup, int(body.execution_group_id), populate_existing=True
    )
    allowed = service._repo.college_ids
    if group is None or (allowed is not None and group.college_id not in allowed):
        raise NotFoundError("执行组不在当前工作区")
    service._generation_scope = resolve_scope(service._session, actor, group.college_id, "inspection.generate", write=True)
    group = service._session.scalar(
        select(VolunteerGroup)
        .where(VolunteerGroup.id == group.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    version = service._session.scalar(
        select(GroupConfigVersion).where(
            GroupConfigVersion.group_id == group.id,
            GroupConfigVersion.college_id == group.college_id,
            GroupConfigVersion.version == group.config_version,
        )
    )
    if group.status != "ACTIVE" or version is None:
        raise ConflictError(message="执行组未启用或未发布范围")
    service._repo.college_ids = frozenset({group.college_id})
    service._generation_group = group, version


def validate(service, plans, *, strict=True):
    if not service._generation_group:
        return plans
    group, version = service._generation_group
    config = version.configuration
    rule = InspectionScope(
        group.college_id,
        frozenset(int(value) for value in config["course_type_ids"]),
        frozenset(int(value) for value in config["class_ids"])
        if config["class_mode"] == "SPECIFIC"
        else None,
    )
    parents = {
        row.id: row
        for row in service._session.scalars(
            select(TeachingClass).where(
                TeachingClass.id.in_(
                    {plan.teaching_class_id for plan in plans if plan.teaching_class_id}
                )
            )
        )
    }
    kinds = {
        row.id: row
        for row in service._session.scalars(
            select(CourseType).where(
                CourseType.id.in_(
                    {row.course_type_id for row in parents.values() if row.course_type_id}
                )
            )
        )
    }
    schedule_teaching = dict(service._session.execute(select(CourseSchedule.id, CourseSchedule.teaching_class_id).where(
        CourseSchedule.id.in_({sid for plan in plans for sid in plan.constituent_schedule_ids})
    )).all())
    allowed = []
    for plan in plans:
        teaching = parents.get(plan.teaching_class_id)
        kind = kinds.get(teaching.course_type_id) if teaching else None
        if (
            kind is None
            or kind.status != "ACTIVE"
            or kind.college_id != group.college_id
            or teaching.status != "ACTIVE"
            or not rule.allows(
                college_id=teaching.college_id,
                course_type_id=kind.id,
                class_ids={row.administrative_class_id_snapshot for row in plan.roster},
            )
            or any(row.college_id_snapshot != group.college_id for row in plan.roster)
            or (group.starts_on and plan.inspection_date < group.starts_on)
            or (group.ends_on and plan.inspection_date > group.ends_on)
            or (getattr(service, "_generation_scope", None) is not None and not service._generation_scope.permits_plan(
                group.id, kind.id, {teaching.id} | {schedule_teaching.get(sid) for sid in plan.constituent_schedule_ids}, {row.administrative_class_id_snapshot for row in plan.roster}))
        ):
            if strict:
                raise ConflictError(
                    message="所选课次未分类、名单不明或超出执行组范围/有效期，整批未生成"
                )
            continue
        allowed.append(plan)
    return allowed
