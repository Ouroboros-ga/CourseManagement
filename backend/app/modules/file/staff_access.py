"""教职工材料与现场照片逐文件访问授权判定。

规则与合同：
1. 账号与档案有效性：统一复用 identity.staff_deps.active_profile（账号、档案、学院三者
   有效且学院与档案同校），不在本模块另写一套判定。
2. 现场照片 (SUBMISSION_PHOTO):
   - 随 SubmissionFile 关联到 InspectionSubmission -> InspectionTask。
   - 若操作者是任务对应教学班的当前任课教师（满足 teaching_class_condition） -> 允许访问。
   - 若操作者是班级责任人（辅导员/班主任）：
     "跨院只读汇总不隐含材料权限" -> 任务所属学院必须为该教工所属学院！
     且任务名单快照中包含属于操作者当前有效责任班级的学生 -> 允许访问。
3. 异议材料 (OBJECTION_PROOF):
   - 随 ObjectionFile 关联到 Objection -> AttendanceRecord -> InspectionTask。
   - "跨院只读汇总不隐含材料权限" -> 任务所属学院必须为该教工所属学院！
   - 且该异议学生在任务名单快照中的行政班属于操作者当前有效责任班级 -> 允许访问。
4. 撤权与状态变更：
   - 每次访问重新实时执行数据库查询，不依赖缓存。撤权/过期后下一次读取立即拒绝。
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.academic.models import TeachingClass
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import AttendanceRecord
from app.modules.file.models import FileCategory, FileObject
from app.modules.identity.role_scope import business_today
from app.modules.identity.staff_deps import active_profile
from app.modules.identity.staff_scope import (
    responsible_class_condition,
    teaching_class_condition,
)
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    SubmissionFile,
    TaskRosterMember,
    TaskScheduleSource,
)
from app.modules.objection.models import Objection, ObjectionFile


def can_staff_access_file(session: Session, actor_user_id: int, file: FileObject) -> bool:
    """判定教职工是否有权访问指定业务材料文件。"""
    staff = active_profile(session, actor_user_id)
    if staff is None:
        return False

    as_of = business_today()

    # 2. 查课现场照片 SUBMISSION_PHOTO
    if file.category == FileCategory.SUBMISSION_PHOTO.value:
        tasks = list(
            session.scalars(
                select(InspectionTask)
                .join(InspectionSubmission, InspectionSubmission.task_id == InspectionTask.id)
                .join(SubmissionFile, SubmissionFile.submission_id == InspectionSubmission.id)
                .where(SubmissionFile.file_id == file.id)
            ).all()
        )
        if not tasks:
            return False

        for task in tasks:
            # A) 授课关系检查：任课教师可看本人授课课次的现场照片
            is_teaching = session.scalar(
                select(TeachingClass.id).where(
                    or_(
                        TeachingClass.id == task.teaching_class_id,
                        select(TaskScheduleSource.task_id)
                        .where(
                            TaskScheduleSource.task_id == task.id,
                            TaskScheduleSource.teaching_class_id == TeachingClass.id,
                        )
                        .exists(),
                    ),
                    teaching_class_condition(
                        actor_user_id, occurrence_on=task.inspection_date, as_of=as_of
                    ),
                )
            )
            if is_teaching is not None:
                return True

            # B) 责任班级检查：
            # 必须本院！"跨院只读汇总不隐含材料权限" -> 异院任务绝不授权照片！
            if task.college_id == staff.college_id:
                has_responsible_student = session.scalar(
                    select(TaskRosterMember.id).where(
                        TaskRosterMember.task_id == task.id,
                        TaskRosterMember.roster_version == task.roster_version,
                        TaskRosterMember.administrative_class_id_snapshot.is_not(None),
                        responsible_class_condition(
                            actor_user_id,
                            administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                            as_of=as_of,
                            review_college_id=task.college_id,
                        ),
                    )
                )
                if has_responsible_student is not None:
                    return True

        return False

    # 3. 异议证明材料 OBJECTION_PROOF
    if file.category == FileCategory.OBJECTION_PROOF.value:
        # 材料可达性经的考勤锚点可能已撤回；证据本身仍须可读，故显式放行隐身行。
        rows = session.execute(
            see_withdrawn(
                select(Objection, InspectionTask)
                .join(ObjectionFile, ObjectionFile.objection_id == Objection.id)
                .join(AttendanceRecord, AttendanceRecord.id == Objection.attendance_record_id)
                .join(InspectionTask, InspectionTask.id == AttendanceRecord.task_id)
                .where(ObjectionFile.file_id == file.id)
            )
        ).all()
        if not rows:
            return False

        for objection, task in rows:
            # 跨院只读不隐含材料权限：必须本院任务
            if task.college_id == staff.college_id:
                has_responsible_student = session.scalar(
                    select(TaskRosterMember.id).where(
                        TaskRosterMember.task_id == task.id,
                        TaskRosterMember.student_id == objection.student_id,
                        TaskRosterMember.roster_version == task.roster_version,
                        TaskRosterMember.administrative_class_id_snapshot.is_not(None),
                        responsible_class_condition(
                            actor_user_id,
                            administrative_class_id=TaskRosterMember.administrative_class_id_snapshot,
                            as_of=as_of,
                            review_college_id=task.college_id,
                        ),
                    )
                )
                if has_responsible_student is not None:
                    return True

        return False

    return False


__all__ = ["can_staff_access_file"]
