"""Configuration changes retain tasks; confirm the exact current future impact."""

import hashlib
import json

from sqlalchemy import or_, select

from app.core.exceptions import ConflictError, ErrorCode
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import InspectionTask, TaskScheduleSource


def future_impact(
    db,
    college_id,
    kind,
    resource_id,
    version,
    *,
    resource_scope=None,
    semester_id=None,
    inherited_only=False,
):
    column = {
        "course_type": InspectionTask.course_type_id_snapshot,
        "group": InspectionTask.group_id,
        "teaching_class": InspectionTask.teaching_class_id,
    }[kind]
    matches = column == resource_id
    if kind == "teaching_class":
        matches = or_(
            matches,
            InspectionTask.id.in_(
                select(TaskScheduleSource.task_id).where(
                    TaskScheduleSource.teaching_class_id == resource_id
                )
            ),
        )
    semester_filter = True
    if semester_id is not None:
        semester_filter = InspectionTask.semester_id == semester_id
    elif inherited_only:
        from app.modules.volunteer.preparation_models import GroupSemesterPreparation

        semester_filter = InspectionTask.semester_id.not_in(
            select(GroupSemesterPreparation.semester_id).where(
                GroupSemesterPreparation.group_id == resource_id,
                GroupSemesterPreparation.college_id == college_id,
            )
        )
    rows = list(
        db.execute(
            select(InspectionTask.id, InspectionTask.lock_version)
            .where(
                InspectionTask.college_id == college_id,
                matches,
                semester_filter,
                InspectionTask.inspection_date >= business_today(),
                InspectionTask.canceled_at.is_(None),
                resource_scope.task_condition() if resource_scope is not None else True,
            )
            .order_by(InspectionTask.id)
            .with_for_update(read=True)
        )
    )
    snapshot = [college_id, kind, resource_id, version, semester_id, [list(row) for row in rows]]
    return {
        "revision": hashlib.sha256(json.dumps(snapshot).encode()).hexdigest(),
        "retained_future_task_ids": [str(row.id) for row in rows],
        "existing_tasks_keep_snapshot": True,
        "existing_assignments_preserved": True,
    }


def confirm_impact(
    db,
    college_id,
    kind,
    row,
    revision,
    *,
    resource_scope=None,
    semester_id=None,
    inherited_only=False,
):
    version = row.classification_revision if kind == "teaching_class" else row.lock_version
    impact = future_impact(
        db,
        college_id,
        kind,
        row.id,
        version,
        resource_scope=resource_scope,
        semester_id=semester_id,
        inherited_only=inherited_only,
    )
    if impact["retained_future_task_ids"] and revision != impact["revision"]:
        raise ConflictError(
            ErrorCode.VERSION_CONFLICT,
            "存在未来任务，请重新查看影响并确认；已有任务保留原快照和受派",
        )
    return impact
