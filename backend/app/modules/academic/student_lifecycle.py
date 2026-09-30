"""学生停用的同事务联动，保留任务、考勤与历史受派。"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.permissions import RoleCode
from app.modules.academic.models import PeriodDefinition, VolunteerQualification
from app.modules.identity.models import BindingTokenStatus, IdentityBindingToken, UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.inspection.models import (
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    TaskDeadlineAssessment,
)


def deactivate_student(session: Session, student_id: int) -> int:
    """调用者已锁学期和学生；返回退出未来任务的数量，不改任何截止考核事实。"""
    repo = IdentityRepository(session)
    now = utcnow()
    for qualification in session.execute(
        select(VolunteerQualification)
        .where(VolunteerQualification.student_id == student_id)
        .with_for_update()
    ).scalars():
        qualification.enabled = False
    users = session.execute(
        select(UserAccount)
        .where(UserAccount.student_id == student_id)
        .order_by(UserAccount.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars()
    user_ids = []
    for user in users:
        user_ids.append(user.id)
        user.student_id = None
        for role_code in (RoleCode.STUDENT.value, RoleCode.STUDENT_AFFAIRS_MANAGER.value):
            role = repo.get_role_by_code(role_code)
            if role is not None:
                repo.revoke_role(user.id, role.id)
        repo.clear_optional_grants(user.id)
        repo.revoke_active_sessions(user.id, now)
        user.lock_version += 1
    for token in session.execute(
        select(IdentityBindingToken)
        .where(
            IdentityBindingToken.student_id == student_id,
            IdentityBindingToken.status == BindingTokenStatus.UNUSED.value,
        )
        .with_for_update()
    ).scalars():
        token.status = BindingTokenStatus.EXPIRED.value
    if not user_ids:
        return 0
    offset = timedelta(hours=get_settings().app_utc_offset_hours)
    rows = session.execute(
        select(InspectionAssignment, InspectionTask, PeriodDefinition.start_time)
        .join(InspectionTask, InspectionTask.id == InspectionAssignment.task_id)
        .outerjoin(
            PeriodDefinition,
            (PeriodDefinition.semester_id == InspectionTask.semester_id)
            & (PeriodDefinition.period_no == InspectionTask.start_period),
        )
        .where(
            InspectionAssignment.volunteer_user_id.in_(user_ids),
            InspectionAssignment.revoked_at.is_(None),
            InspectionTask.canceled_at.is_(None),
            InspectionTask.inspection_date >= (now + offset).date(),
        )
        .order_by(InspectionTask.id)
        .with_for_update()
    ).all()
    changed = 0
    for assignment, task, start_time in rows:
        # 缺少节次时只撤明天以后的任务，不猜测今天任务是否已经开始。
        future = (
            datetime.combine(task.inspection_date, start_time) - offset > now
            if start_time is not None
            else task.inspection_date > (now + offset).date()
        )
        if not future:
            continue
        has_facts = any(
            session.execute(
                select(model.id).where(model.task_id == task.id).limit(1).with_for_update()
            ).first()
            is not None
            for model in (InspectionSubmission, TaskDeadlineAssessment)
        )
        if has_facts:
            continue
        assignment.revoked_at = now
        task.lock_version += 1
        changed += 1
    session.flush()
    return changed
