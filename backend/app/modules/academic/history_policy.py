"""本人离校历史查询期限；不自动删除机构保留的业务事实。"""

from sqlalchemy import select

from app.core.exceptions import PermissionDeniedError
from app.modules.academic.models import Student
from app.modules.identity.authorization import business_today
from app.modules.identity.models import UserAccount


def self_history_available(db, user_id: int) -> bool:
    user, student = UserAccount.__table__, Student.__table__
    limit = db.scalar(
        select(student.c.history_until)
        .select_from(user.join(student, user.c.student_id == student.c.id))
        .where(user.c.id == user_id)
    )
    return limit is None or business_today() <= limit


def require_self_history(db, user_id: int) -> None:
    if not self_history_available(db, user_id):
        raise PermissionDeniedError("本人离校历史查询期限已届满")
