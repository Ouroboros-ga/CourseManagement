"""明确学院学期重置；先核对完整外键边界，再按依赖顺序删除。"""

import hashlib
import json

from sqlalchemy import and_, delete, exists, not_, or_, select

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.modules.audit.models import AuditLog
from app.modules.audit.provenance import scoped_snapshot

CHILDREN = frozenset(
    {
        "course_schedule_week",
        "teaching_class_student",
        "teaching_class_audience",
        "course_participation",
        "inspection_assignment",
        "assignment_change_request",
        "inspection_submission",
        "submission_abnormal_item",
        "submission_file",
        "task_deadline_assessment",
        "task_roster_member",
        "task_roster_version",
        "attendance_record",
        "attendance_record_version",
        "objection",
        "objection_file",
        "task_schedule_source",
    }
)


def snapshot(service, semester):
    tables = Base.metadata.tables
    data = {
        "college_id": service.college_id,
        "semester_id": semester.id,
        "semester_name": semester.name,
    }
    roots = ("inspection_task", "course_schedule", "teaching_class", "volunteer_qualification")
    counts = {}
    identifiers = {}
    for name in roots:
        table = tables[name]
        rows = list(
            service.db.execute(
                select(table)
                .where(table.c.college_id == service.college_id, table.c.semester_id == semester.id)
                .order_by(table.c.id)
                .with_for_update(read=True)
            ).mappings()
        )
        data[name] = [dict(row) for row in rows]
        identifiers[name] = [row["id"] for row in rows]
        counts[name] = len(rows)
    for name, foreign, parent in (
        ("course_schedule_week", "schedule_id", "course_schedule"),
        ("teaching_class_student", "teaching_class_id", "teaching_class"),
        ("teaching_class_audience", "teaching_class_id", "teaching_class"),
        ("course_participation", "teaching_class_id", "teaching_class"),
    ):
        table = tables[name]
        data[name] = [
            dict(row)
            for row in service.db.execute(
                select(table)
                .where(table.c[foreign].in_(identifiers[parent]))
                .order_by(*table.primary_key.columns)
                .with_for_update(read=True)
            ).mappings()
        ]
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "source_revision": digest,
        "college_id": str(service.college_id),
        "semester_id": str(semester.id),
        "tasks": counts["inspection_task"],
        "schedules": counts["course_schedule"],
        "teaching_classes": counts["teaching_class"],
        "qualifications": counts["volunteer_qualification"],
    }


def reset(service, semester, body):
    tables = Base.metadata.tables
    roots = ["inspection_task", "course_schedule", "teaching_class", "volunteer_qualification"]
    selected = {}
    counts = {}
    for name in roots:
        table = tables[name]
        ids = list(
            service.db.scalars(
                select(table.c.id)
                .where(table.c.college_id == service.college_id, table.c.semester_id == semester.id)
                .order_by(table.c.id)
                .with_for_update()
            )
        )
        selected[name] = table.c.id.in_(ids)
        counts[name] = len(ids)

    def referencing(constraint):
        parent = constraint.referred_table
        return exists(
            select(1)
            .select_from(parent)
            .where(
                selected[parent.name],
                *(element.parent == element.column for element in constraint.elements),
            )
        ).correlate(constraint.table)

    # sorted_tables 保证父表先于子表；根集合固定，绝不沿外院引用扩大删除范围。
    for table in Base.metadata.sorted_tables:
        if table.name not in CHILDREN:
            continue
        conditions = [
            referencing(fk)
            for fk in table.foreign_key_constraints
            if fk.referred_table.name in selected
        ]
        if conditions:
            selected[table.name] = or_(*conditions)

    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            if fk.referred_table.name not in selected:
                continue
            reference = referencing(fk)
            outside = (
                and_(reference, not_(selected[table.name])) if table.name in selected else reference
            )
            if service.db.scalar(select(1).select_from(table).where(outside).limit(1)):
                raise ConflictError(
                    message="存在重置范围外的历史或跨院引用，整批未重置；请先处理依赖"
                )
            if table.name in selected and service.db.scalar(
                select(1)
                .select_from(table)
                .where(
                    selected[table.name],
                    *(element.parent.is_not(None) for element in fk.elements),
                    not_(reference),
                )
                .limit(1)
            ):
                raise ConflictError(message="业务资料引用了范围外父记录，整批未重置")
        if table.name in selected and "college_id" in table.c:
            if service.db.scalar(
                select(1)
                .select_from(table)
                .where(
                    selected[table.name],
                    or_(table.c.college_id.is_(None), table.c.college_id != service.college_id),
                )
                .limit(1)
            ):
                raise ConflictError(message="资料父链学院不一致，整批未重置")

    weeks = set(
        service.db.scalars(
            select(tables["inspection_task"].c.week_no).where(selected["inspection_task"])
        )
    )
    # 子表条件可能引用父表；反向删除时父表尚在，保持集合可复核。
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in selected:
            service.db.execute(delete(table).where(selected[table.name]))
    from app.modules.report.models import ReportSourceRevision

    for week in weeks:
        row = service.db.scalar(
            select(ReportSourceRevision)
            .where(
                ReportSourceRevision.ownership_scope_id == service.college_id,
                ReportSourceRevision.semester_id == semester.id,
                ReportSourceRevision.week_no == week,
            )
            .with_for_update()
        )
        if row:
            row.revision += 1
        else:
            service.db.add(
                ReportSourceRevision(
                    ownership_scope_id=service.college_id,
                    semester_id=semester.id,
                    week_no=week,
                    revision=1,
                )
            )
    result = {
        "semester_id": str(semester.id),
        "cleared_tasks_count": counts["inspection_task"],
        "cleared_schedules_count": counts["course_schedule"],
        "cleared_teaching_classes_count": counts["teaching_class"],
        "cleared_volunteer_qualifications_count": counts["volunteer_qualification"],
        "cleared_calendar_overrides_count": 0,
    }
    service.db.add(
        AuditLog(
            actor_user_id=service.actor.id,
            action="academic.semester.reset_data",
            resource_type="semester",
            resource_id=str(semester.id),
            after_json=scoped_snapshot(result, service.college_id),
            reason=body.reason,
            request_id=service.request_id,
        )
    )
    service.db.commit()
    service.db.expire_all()
    return result
