"""列表专用 SQL 表达式：筛选发生在 LIMIT 前，不装配全量任务。"""

from sqlalchemy import String, and_, case, cast, func, or_, select

from app.core.database import utcnow
from app.modules.academic.models import (
    AdministrativeClass,
    Student,
    TeachingClass,
    TeachingClassStudent,
)
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    SubmissionDeadlineDay,
)


def assigned_expression():
    return (
        select(InspectionAssignment.id)
        .where(
            InspectionAssignment.task_id == InspectionTask.id,
            InspectionAssignment.revoked_at.is_(None),
        )
        .correlate(InspectionTask)
        .exists()
    )


def task_status_expression():
    def submitted(status):
        return (
            select(InspectionSubmission.id)
            .where(
                InspectionSubmission.task_id == InspectionTask.id,
                InspectionSubmission.review_status == status,
            )
            .correlate(InspectionTask)
            .exists()
        )

    overdue = (
        select(SubmissionDeadlineDay.id)
        .where(
            or_(
                SubmissionDeadlineDay.id == InspectionTask.deadline_day_id,
                and_(
                    InspectionTask.deadline_day_id.is_(None),
                    SubmissionDeadlineDay.ownership_scope_id == 0,
                    SubmissionDeadlineDay.semester_id == InspectionTask.semester_id,
                    SubmissionDeadlineDay.inspection_date == InspectionTask.inspection_date,
                ),
            ),
            SubmissionDeadlineDay.deadline_at < utcnow(),
        )
        .correlate(InspectionTask)
        .exists()
    )
    return case(
        (InspectionTask.canceled_at.is_not(None), "CANCELLED"),
        (submitted("APPROVED"), "REVIEWED"),
        (submitted("PENDING"), "SUBMITTED"),
        (overdue, "OVERDUE"),
        else_="NOT_STARTED",
    )


def pending_change_expression():
    # 与装配逻辑一致：仅当前受派人的有效申请，旧受派不会混入。
    return (
        select(InspectionAssignment.id)
        .join(
            AssignmentChangeRequest,
            AssignmentChangeRequest.assignment_id == InspectionAssignment.id,
        )
        .where(
            InspectionAssignment.task_id == InspectionTask.id,
            InspectionAssignment.revoked_at.is_(None),
            AssignmentChangeRequest.request_user_id == InspectionAssignment.volunteer_user_id,
            AssignmentChangeRequest.status == "PENDING",
        )
        .correlate(InspectionTask)
        .exists()
    )


def task_search_expression(keyword):
    def matches(column):
        return func.lower(column).contains(keyword.lower(), autoescape=True)

    class_ids = (
        select(Student.administrative_class_id)
        .join(
            TeachingClassStudent,
            TeachingClassStudent.student_id == Student.id,
        )
        .where(TeachingClassStudent.teaching_class_id == InspectionTask.teaching_class_id)
        .correlate(InspectionTask)
    )
    return or_(
        *(
            matches(c)
            for c in (
                cast(InspectionTask.id, String),
                InspectionTask.course_name_snapshot,
                InspectionTask.class_name_snapshot,
                InspectionTask.classroom_snapshot,
                InspectionTask.teacher_name_snapshot,
            )
        ),
        select(TeachingClass.id)
        .where(
            TeachingClass.id == InspectionTask.teaching_class_id,
            matches(TeachingClass.teacher_name),
        )
        .correlate(InspectionTask)
        .exists(),
        select(AdministrativeClass.id)
        .where(
            or_(
                AdministrativeClass.id == InspectionTask.administrative_class_id,
                AdministrativeClass.id.in_(class_ids),
            ),
            or_(
                *(
                    matches(c)
                    for c in (
                        AdministrativeClass.class_name,
                        AdministrativeClass.head_teacher,
                        AdministrativeClass.counselor,
                    )
                )
            ),
        )
        .correlate(InspectionTask)
        .exists(),
        select(InspectionAssignment.id)
        .join(UserAccount, UserAccount.id == InspectionAssignment.volunteer_user_id)
        .outerjoin(Student, Student.id == UserAccount.student_id)
        .where(
            InspectionAssignment.task_id == InspectionTask.id,
            InspectionAssignment.revoked_at.is_(None),
            or_(matches(UserAccount.display_name), matches(Student.name)),
        )
        .correlate(InspectionTask)
        .exists(),
        select(InspectionAssignment.id)
        .join(
            AssignmentChangeRequest,
            AssignmentChangeRequest.assignment_id == InspectionAssignment.id,
        )
        .where(
            InspectionAssignment.task_id == InspectionTask.id,
            InspectionAssignment.revoked_at.is_(None),
            AssignmentChangeRequest.request_user_id == InspectionAssignment.volunteer_user_id,
            matches(AssignmentChangeRequest.reason),
        )
        .correlate(InspectionTask)
        .exists(),
    )
