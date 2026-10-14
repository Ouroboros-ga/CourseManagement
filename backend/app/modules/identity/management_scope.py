"""管理查询的 SQL 学院范围；None 仅代表数据库确认的校级超管。"""

from sqlalchemy.orm import Session

from app.modules.identity.role_scope import active_manager_appointment, business_today
from app.modules.identity.service import CurrentUser
from app.modules.organization.service import CampusService


def management_college_ids(db: Session, actor: CurrentUser, action: str) -> frozenset[int] | None:
    service = CampusService(db)
    if service._actor(actor):
        return None
    ids = {
        int(row["id"])
        for row in service.workspaces(actor)
        if row["status"] == "ACTIVE" and action in row["capabilities"]
    }
    if "STUDENT_AFFAIRS_MANAGER" in service.identity.list_role_codes(actor.id):
        appointment = active_manager_appointment(db, actor.id, business_today())
        if appointment and action in appointment.allowed_actions:
            college = service.repo.college(appointment.college_id)
            if college and college.status == "ACTIVE":
                ids.add(college.id)
    return frozenset(ids)
