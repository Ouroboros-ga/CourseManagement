"""Typed resource ceilings; a limited action never becomes a college-wide grant."""

from sqlalchemy import and_, false, or_, select

TASK_ACTIONS = frozenset({
    "inspection.read", "inspection.roster.read", "inspection.roster.manage", "inspection.generate",
    "inspection.cancel", "assignment.manage", "assignment.change_review", "submission.read",
    "submission.review", "attendance.read", "attendance.correct", "attendance.expected_count_adjust",
    "objection.read", "objection.final_review",
})
GROUP_ACTIONS = frozenset({"volunteer.group.read", "volunteer.group.manage",
    "volunteer.member.manage", "volunteer.config.publish"})
LIMITED_ACTIONS = TASK_ACTIONS | GROUP_ACTIONS


def resource_definition(grant):
    return getattr(grant, "resource_scope", None) or {"kind": "COLLEGE", "ids": []}


def is_whole_college(grant):
    return resource_definition(grant).get("kind") == "COLLEGE"


def active_grants(grants, cid, now, action):
    return [grant for grant in grants if grant.college_id == cid and grant.status == "ACTIVE"
            and action in grant.actions and (grant.starts_at is None or grant.starts_at <= now)
            and (grant.expires_at is None or grant.expires_at > now)]


def permits_group(clauses, gid):
    return any(clause.get("kind") == "GROUPS" and str(gid) in clause.get("ids", []) for clause in clauses)


def permits_plan(clauses, gid, type_id, teaching_ids, class_ids):
    for clause in clauses:
        ids = {int(value) for value in clause.get("ids", [])}
        if clause["kind"] == "COURSE_TYPES" and type_id in ids:
            return True
        if clause["kind"] == "TEACHING_CLASSES" and teaching_ids and teaching_ids <= ids:
            return True
        if clause["kind"] == "GROUPS" and gid in ids:
            bound = clause.get("bounds", {}).get(str(gid), {})
            if str(type_id) in bound.get("course_type_ids", []) and class_ids and None not in class_ids:
                if bound.get("class_mode") == "ALL_AUTHORIZED" or class_ids <= {int(value) for value in bound.get("class_ids", [])}:
                    return True
    return False


def task_condition(cid, clauses):
    from app.modules.inspection.models import InspectionTask as Task
    from app.modules.inspection.models import TaskRosterMember, TaskScheduleSource

    conditions = []
    for clause in clauses:
        ids = [int(value) for value in clause.get("ids", [])]
        if clause["kind"] == "COURSE_TYPES":
            conditions.append(Task.course_type_id_snapshot.in_(ids))
        elif clause["kind"] == "TEACHING_CLASSES":
            conditions.append(and_(Task.teaching_class_id.in_(ids), ~select(TaskScheduleSource.task_id).where(
                TaskScheduleSource.task_id == Task.id, TaskScheduleSource.teaching_class_id.not_in(ids)
            ).exists()))
        elif clause["kind"] == "GROUPS":
            for gid in ids:
                bound = clause.get("bounds", {}).get(str(gid), {})
                allowed = and_(Task.group_id == gid, Task.course_type_id_snapshot.in_(
                    [int(value) for value in bound.get("course_type_ids", [])]))
                if bound.get("class_mode") != "ALL_AUTHORIZED":
                    classes = [int(value) for value in bound.get("class_ids", [])]
                    unknown = or_(TaskRosterMember.administrative_class_id_snapshot.is_(None),
                        TaskRosterMember.administrative_class_id_snapshot.not_in(classes))
                    allowed = and_(allowed, ~select(TaskRosterMember.id).where(
                        TaskRosterMember.task_id == Task.id,
                        TaskRosterMember.roster_version == Task.roster_version, unknown,
                    ).exists(), or_(Task.administrative_class_id.is_(None), Task.administrative_class_id.in_(classes)))
                    known = select(TaskRosterMember.id).where(
                        TaskRosterMember.task_id == Task.id,
                        TaskRosterMember.roster_version == Task.roster_version,
                        TaskRosterMember.administrative_class_id_snapshot.in_(classes),
                    ).exists()
                    allowed = and_(allowed, or_(Task.administrative_class_id.in_(classes), known))
                conditions.append(allowed)
    return and_(Task.college_id == cid, or_(*conditions) if conditions else false())
