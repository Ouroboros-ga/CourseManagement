"""分页后批量装配申请展示上下文，不加载全班名单或逐行查询账号。"""

from sqlalchemy import select

from app.modules.academic.models import Semester, Student
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionAssignment, InspectionSubmission, InspectionTask


def enrich_requests(db, rows, dto):
    if not rows:
        return []
    assignment_ids = [req.assignment_id for req, _ in rows]
    context = {
        assignment.id: (assignment, task, semester_status)
        for assignment, task, semester_status in db.execute(
            select(InspectionAssignment, InspectionTask, Semester.status)
            .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
            .join(Semester, Semester.id == InspectionTask.semester_id)
            .where(InspectionAssignment.id.in_(assignment_ids))
        )
    }
    user_ids = {req.request_user_id for req, _ in rows} | {
        req.processed_by for req, _ in rows if req.processed_by is not None
    }
    people = {
        uid: (name, number)
        for uid, name, number in db.execute(
            select(UserAccount.id, UserAccount.display_name, Student.student_no)
            .outerjoin(Student, Student.id == UserAccount.student_id)
            .where(UserAccount.id.in_(user_ids))
        )
    }
    submitted = set(
        db.scalars(
            select(InspectionSubmission.task_id).where(
                InspectionSubmission.task_id.in_([tid for _, tid in rows]),
                InspectionSubmission.review_status.in_(["PENDING", "APPROVED"]),
            )
        )
    )
    result = []
    for req, tid in rows:
        item = dto(req, tid).model_dump()
        assignment, task, semester_status = context[req.assignment_id]
        blocked = (
            "受派已失效"
            if assignment.revoked_at is not None
            or assignment.volunteer_user_id != req.request_user_id
            else "任务已删除"
            if task.deleted_at
            else "任务已取消"
            if task.canceled_at
            else "任务已记为异常，请先恢复"
            if task.exception_reported_at
            else "学期已归档"
            if semester_status != "ACTIVE"
            else "任务已有正式或待审核提交"
            if task.id in submitted
            else None
        )
        name, number = people.get(req.request_user_id, (None, None))
        item.update(
            requester_name=name,
            requester_student_no=number,
            processor_name=people.get(req.processed_by, (None, None))[0],
            semester_id=str(task.semester_id),
            inspection_date=task.inspection_date,
            course_name=task.course_name_snapshot,
            class_name=task.class_name_snapshot,
            classroom=task.classroom_snapshot,
            start_period=task.start_period,
            end_period=task.end_period,
            time_snapshot=task.time_snapshot,
            activity_start_at=task.activity_start_at,
            activity_end_at=task.activity_end_at,
            can_process=req.status == "PENDING" and blocked is None,
            blocked_reason=blocked if req.status == "PENDING" else None,
        )
        result.append(item)
    return result
