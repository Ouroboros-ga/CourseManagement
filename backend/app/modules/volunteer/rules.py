"""任务使用已冻结的组规则；成员与支援按执行日期重新核验。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.modules.academic.campus_models import CourseType
from app.modules.inspection.models import InspectionAssignment, InspectionTask, TaskRosterMember
from app.modules.inspection.task_time import task_minutes
from app.modules.volunteer.models import GroupConfigVersion, VolunteerGroup
from app.modules.volunteer.policy import course_conflict_effect


class GroupRules:
    def __init__(self, db: Session, task: InspectionTask):
        self.db, self.task = db, task
        self.group = db.scalar(
            select(VolunteerGroup)
            .where(VolunteerGroup.id == task.group_id, VolunteerGroup.college_id == task.college_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        version = db.scalar(
            select(GroupConfigVersion).where(
                GroupConfigVersion.id == task.group_config_version_id,
                GroupConfigVersion.group_id == task.group_id,
                GroupConfigVersion.college_id == task.college_id,
            )
        )
        if self.group is None or self.group.status != "ACTIVE" or version is None:
            raise ConflictError(message="任务组已停用或规则快照不属于该组")
        from app.modules.volunteer.preparation_models import semester_group_config
        current = semester_group_config(db, self.group, task.semester_id)
        if current is None or current.id != version.id:
            raise ConflictError(message="组配置已更新，请先预览并确认任务执行组/规则后重新排班")
        from app.modules.academic.models import TeachingClass
        from app.modules.inspection.models import TaskScheduleSource
        teaching_ids = set(db.scalars(select(TaskScheduleSource.teaching_class_id).where(
            TaskScheduleSource.task_id == task.id)))
        if task.teaching_class_id:
            teaching_ids.add(task.teaching_class_id)
        teaching = list(db.scalars(select(TeachingClass).where(
            TeachingClass.id.in_(teaching_ids)).with_for_update(read=True)))
        if not teaching or len(teaching) != len(teaching_ids) or any(
            row.status != "ACTIVE" or row.college_id != task.college_id
            or row.course_type_id != task.course_type_id_snapshot
            or (row.id == task.teaching_class_id
                and row.classification_revision != task.classification_revision_snapshot)
            for row in teaching
        ):
            raise ConflictError(message="教学班分类或状态已变化，请先确认任务执行组/分类后重新排班")
        if (self.group.starts_on and task.inspection_date < self.group.starts_on) or (
            self.group.ends_on and task.inspection_date > self.group.ends_on
        ):
            raise ConflictError(message="任务日期不在组有效期内")
        self.config = version.configuration
        if self.config.get("class_mode") == "SPECIFIC":
            allowed = {int(value) for value in self.config.get("class_ids", [])}
            classes = (
                set(
                    db.scalars(
                        select(TaskRosterMember.administrative_class_id_snapshot).where(
                            TaskRosterMember.task_id == task.id,
                            TaskRosterMember.roster_version == task.roster_version,
                        )
                    )
                )
                if task.id is not None
                else set()
            )
            if task.administrative_class_id is not None:
                classes.add(task.administrative_class_id)
            if not classes or None in classes or not classes.issubset(allowed):
                raise ConflictError(message="任务名单班级未确认或超出组冻结的指定班级范围")
        target_type = db.scalar(
            select(CourseType)
            .where(
                CourseType.id == task.course_type_id_snapshot,
                CourseType.college_id == task.college_id,
                CourseType.status == "ACTIVE",
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if target_type is None or str(target_type.id) not in self.config["course_type_ids"]:
            raise ConflictError(message="任务类型未分类、已停用或不在组查课范围")

    def member_allowed(self, student_id: int) -> bool:
        from app.modules.volunteer.eligibility_index import EligibilityIndex

        return EligibilityIndex(self.db, [student_id], [self.task], lock=True).member_allowed(
            self.task, student_id
        )

    def course_effect(self, teaching_class_id: int, course_type_id: int | None):
        return course_conflict_effect(
            course_type_id,
            teaching_class_id,
            self.config["default_effect"],
            {int(k): v for k, v in self.config.get("type_overrides", {}).items()},
            {int(k): v for k, v in self.config.get("teaching_class_overrides", {}).items()},
        )

    def interval(self):
        start, end = task_minutes(self.task)
        buffer = self.config.get("buffer_minutes", 0)
        return start - buffer, end + buffer

    def limit_reason(self, user_id: int):
        from datetime import timedelta

        task = self.task
        monday = task.inspection_date - timedelta(days=task.inspection_date.weekday())
        stmt = (
            select(InspectionTask.inspection_date)
            .join(InspectionAssignment, InspectionAssignment.task_id == InspectionTask.id)
            .where(
                InspectionAssignment.volunteer_user_id == user_id,
                InspectionAssignment.revoked_at.is_(None),
                InspectionTask.canceled_at.is_(None),
                InspectionTask.id != task.id,
                InspectionTask.inspection_date >= monday,
                InspectionTask.inspection_date < monday + timedelta(days=7),
            )
        )
        if self.config.get("count_scope") == "GROUP":
            stmt = stmt.where(InspectionTask.group_id == task.group_id)
        dates = list(self.db.scalars(stmt.with_for_update(read=True)))
        if dates.count(task.inspection_date) >= self.config["daily_limit"]:
            return "DAY_CAP_EXCEEDED"
        if len(dates) >= self.config["weekly_limit"]:
            return "WEEK_CAP_EXCEEDED"
        return None


def assignment_interval(db: Session, task: InspectionTask):
    start, end = task_minutes(task)
    if task.group_id:
        version = db.scalar(
            select(GroupConfigVersion).where(
                GroupConfigVersion.id == task.group_config_version_id,
                GroupConfigVersion.group_id == task.group_id,
                GroupConfigVersion.college_id == task.college_id,
            )
        )
        if version is None:
            raise ConflictError(message="既有受派缺少可靠组规则快照")
        buffer = version.configuration.get("buffer_minutes", 0)
        return start - buffer, end + buffer
    return start, end
