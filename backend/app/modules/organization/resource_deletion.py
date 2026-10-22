"""Versioned management deletion; immutable operational history is never cascaded."""

import uuid

from sqlalchemy import select

from app.core.database import Base, utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.role_scope import business_today
from app.modules.inspection.assignment_fingerprint import fingerprint
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from app.modules.organization.models import ScopedGrant
from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup


def settings(kind):
    return (
        (VolunteerGroup, "volunteer.group.manage")
        if kind == "group"
        else (CourseType, "academic.course_type.manage")
    )


def preview(service, actor, cid, kind, rid):
    model, action = settings(kind)
    college = service._authorize(actor, cid, action, write=True)
    row = service._resource(model, cid, rid)
    refs = {}
    for table in Base.metadata.sorted_tables:
        if kind == "group" and table.name == "group_config_version":
            continue
        for fk in table.foreign_keys:
            if (
                fk.column.table.name == model.__tablename__
                and fk.column.name == "id"
                and service.db.execute(
                    select(fk.parent).where(fk.parent == rid).limit(1).with_for_update(read=True)
                ).first()
            ):
                refs[table.name] = True
    versions = (
        list(
            service.db.scalars(
                select(GroupConfigVersion.id).where(GroupConfigVersion.group_id == rid)
            )
        )
        if kind == "group"
        else []
    )
    for table in Base.metadata.sorted_tables:
        if table.name == "group_scope_type" or not versions:
            continue
        for fk in table.foreign_keys:
            if (
                fk.column.table.name == "group_config_version"
                and fk.column.name == "id"
                and service.db.execute(
                    select(fk.parent)
                    .where(fk.parent.in_(versions))
                    .limit(1)
                    .with_for_update(read=True)
                ).first()
            ):
                refs[table.name] = True
    column = InspectionTask.group_id if kind == "group" else InspectionTask.course_type_id_snapshot
    if service.db.scalar(
        select(InspectionTask.id).where(column == rid).limit(1).with_for_update(read=True)
    ):
        refs["inspection_task_snapshot"] = True
    pending = list(
        service.db.scalars(
            see_withdrawn(
                select(InspectionTask.id)
                .where(
                    InspectionTask.college_id == cid,
                    column == rid,
                    InspectionTask.inspection_date >= business_today(),
                    InspectionTask.canceled_at.is_(None),
                    InspectionTask.deleted_at.is_(None),
                    ~select(InspectionSubmission.id)
                    .where(InspectionSubmission.task_id == InspectionTask.id)
                    .exists(),
                    ~select(AttendanceRecord.id)
                    .where(AttendanceRecord.task_id == InspectionTask.id)
                    .exists(),
                )
                .order_by(InspectionTask.id)
                .with_for_update(read=True)
            )
        )
    )
    mode = "RETAIN_HISTORY" if refs or getattr(row, "builtin_key", None) else "PERMANENT"
    plan = {
        "resource_id": str(rid),
        "mode": mode,
        "references": sorted(refs),
        "blocking_task_ids": [str(i) for i in pending],
        "can_delete": not pending,
        "history_preserved": mode == "RETAIN_HISTORY",
    }
    plan["revision"] = fingerprint(
        {
            "row": service._dto(row),
            "plan": plan,
            "college_revision": college.configuration_revision,
            "authorization_revision": college.authorization_revision,
        }
    )
    return college, row, plan


def delete_resource(service, actor, cid, kind, rid, version, revision):
    college, row, plan = preview(service, actor, cid, kind, rid)
    service._version(row, version)
    if not plan["can_delete"]:
        raise ConflictError(message="仍有待执行任务，请先取消或转组后重新预览删除影响")
    if revision != plan["revision"] and (revision is not None or plan["mode"] != "PERMANENT"):
        raise ConflictError(message="请重新预览删除影响后确认，资料或引用可能已变化")
    if plan["mode"] == "PERMANENT":
        method = service._legacy_delete_group if kind == "group" else service._legacy_delete_type
        method(actor, cid, rid, version)
        return plan
    before = service._dto(row)
    row.deleted_at, row.status = utcnow(), "INACTIVE"
    row.normalized_name = "deleted:" + str(row.id) + ":" + uuid.uuid4().hex
    row.lock_version += 1
    college.configuration_revision += 1
    if kind == "group":
        for grant in service.db.scalars(
            select(ScopedGrant)
            .where(ScopedGrant.owner_group_id == rid, ScopedGrant.status == "ACTIVE")
            .with_for_update()
        ):
            grant_before = service._dto(grant)
            grant.status = "REVOKED"
            grant.lock_version += 1
            college.authorization_revision += 1
            service.db.add(
                AuditLog(
                    actor_user_id=actor.id,
                    action="campus.grant.revoke_group_deleted",
                    resource_type="ScopedGrant",
                    resource_id=str(grant.id),
                    before_json=grant_before,
                    after_json={"status": "REVOKED", "college_id": str(cid)},
                    request_id=service.request_id,
                )
            )
    service._commit(
        actor,
        "campus." + ("group" if kind == "group" else "type") + ".delete_retained",
        row,
        before,
    )
    return plan


def restore(service, actor, cid, kind, rid, version, name):
    from app.modules.organization.service import normalized_name

    model, action = settings(kind)
    college = service._authorize(actor, cid, action, write=True)
    row = service.db.scalar(
        select(model)
        .where(model.college_id == cid, model.id == rid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.deleted_at is None:
        raise NotFoundError("已删除记录不存在")
    service._version(row, version)
    before = service._dto(row)
    row.name = name.strip() if name else row.name
    row.normalized_name = normalized_name(row.name)
    row.deleted_at, row.status = None, "INACTIVE"
    row.lock_version += 1
    college.configuration_revision += 1
    return service._commit(actor, "campus.resource.restore", row, before)
