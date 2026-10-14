"""考勤与现场照片的统一关联谓词；列表和文件鉴权共享可见性规则。"""

from sqlalchemy import func, select

from app.modules.attendance.models import AttendanceRecord
from app.modules.file.models import FileObject
from app.modules.inspection.models import InspectionSubmission, SubmissionFile, TaskRosterMember


def attendance_photo_query():
    # 任务锁保证只有一条 APPROVED；历史补偿数据出现多条时仅取最后通过的提交。
    approved = (
        select(InspectionSubmission.task_id,
               func.max(InspectionSubmission.attempt_no).label("attempt_no"))
        .where(InspectionSubmission.review_status == "APPROVED")
        .group_by(InspectionSubmission.task_id).subquery()
    )
    return (
        select(AttendanceRecord.id.label("record_id"), SubmissionFile.file_id)
        .join(approved, approved.c.task_id == AttendanceRecord.task_id)
        .join(InspectionSubmission,
              (InspectionSubmission.task_id == approved.c.task_id)
              & (InspectionSubmission.attempt_no == approved.c.attempt_no))
        .join(TaskRosterMember,
              (TaskRosterMember.task_id == AttendanceRecord.task_id)
              & (TaskRosterMember.roster_version == InspectionSubmission.roster_version)
              & (TaskRosterMember.student_id == AttendanceRecord.student_id))
        .join(SubmissionFile, SubmissionFile.submission_id == InspectionSubmission.id)
        .join(FileObject, FileObject.id == SubmissionFile.file_id)
        .where(FileObject.category == "SUBMISSION_PHOTO")
    )
