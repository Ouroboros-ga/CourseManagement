"""跨任务学生可见范围：SQL 聚合与导出复用冻结教学班归属，不加载全量学生。"""

from datetime import date

from sqlalchemy import and_, or_, select

from app.modules.academic.models import TeachingClass
from app.modules.identity.staff_scope import teaching_class_condition
from app.modules.inspection.models import (
    InspectionTask,
    TaskRosterMember,
    TaskRosterMemberClass,
    TaskScheduleSource,
)


def teaching_student_condition(user_id: int, as_of: date):
    """单班整班可读；合班仅命中本人归属或缺少历史归属的学生可读。

    必须用于已按当前名单版本关联的 AttendanceRecord / TaskRosterMember 查询。
    可读不代表可更正；写入口继续执行原有完整归属与版本检查。
    """
    source_hit = (
        select(TaskScheduleSource.task_id)
        .where(
            TaskScheduleSource.task_id == InspectionTask.id,
            TaskScheduleSource.teaching_class_id == TeachingClass.id,
        )
        .correlate(InspectionTask, TeachingClass)
        .exists()
    )
    other_source = (
        select(TaskScheduleSource.task_id)
        .where(
            TaskScheduleSource.task_id == InspectionTask.id,
            TaskScheduleSource.teaching_class_id != TeachingClass.id,
        )
        .correlate(InspectionTask, TeachingClass)
        .exists()
    )
    covered = and_(
        or_(TeachingClass.id == InspectionTask.teaching_class_id, source_hit),
        teaching_class_condition(
            user_id, occurrence_on=InspectionTask.inspection_date, as_of=as_of
        ),
    )
    whole_class = (
        select(TeachingClass.id)
        .where(
            covered,
            or_(
                InspectionTask.teaching_class_id.is_(None),
                InspectionTask.teaching_class_id == TeachingClass.id,
            ),
            ~other_source,
        )
        .correlate(InspectionTask)
        .exists()
    )
    member_match = (
        TaskRosterMemberClass.task_id == TaskRosterMember.task_id,
        TaskRosterMemberClass.roster_version == TaskRosterMember.roster_version,
        TaskRosterMemberClass.student_id == TaskRosterMember.student_id,
    )
    any_membership = (
        select(TaskRosterMemberClass.id)
        .where(*member_match)
        .correlate(TaskRosterMember)
        .exists()
    )
    own_membership = (
        select(TaskRosterMemberClass.id)
        .join(TeachingClass, TeachingClass.id == TaskRosterMemberClass.teaching_class_id)
        .where(*member_match, covered)
        .correlate(TaskRosterMember, InspectionTask)
        .exists()
    )
    return or_(whole_class, ~any_membership, own_membership)
