"""动作与学院完整绑定的不可变查询范围；不是客户端传入的学院列表。"""

from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy.orm import Session

from app.modules.identity.authorization import CAMPUS_ACTIONS
from app.modules.identity.service import CurrentUser
from app.modules.organization.service import CampusService


@dataclass(frozen=True)
class ResourceScope:
    actor_user_id: int
    college_id: int
    action: str
    authorization_revision: int
    unrestricted: bool = True
    constraints: tuple = ()

    def task_condition(self):
        from app.modules.identity.grant_scope import task_condition
        from app.modules.inspection.models import InspectionTask
        return (InspectionTask.college_id == self.college_id if self.unrestricted
                else task_condition(self.college_id, self.constraints))

    def permits_group(self, gid):
        from app.modules.identity.grant_scope import permits_group
        return self.unrestricted or permits_group(self.constraints, gid)

    def permits_plan(self, gid, type_id, teaching_ids, class_ids):
        from app.modules.identity.grant_scope import permits_plan
        return self.unrestricted or permits_plan(self.constraints, gid, type_id, teaching_ids, class_ids)

    def __post_init__(self):
        if (
            not 0 < self.actor_user_id < 2**63
            or not 0 < self.college_id < 2**63
            or self.action not in CAMPUS_ACTIONS
            or self.authorization_revision < 1
        ):
            raise ValueError("必须提供有效操作者、学院、动作和授权修订")


def resolve_scope(
    db: Session, actor: CurrentUser, college_id: int, action: str, *, write: bool = False
) -> ResourceScope:
    # 复用账号、实际角色、有效授权及学院锁；不能信任缓存的角色标签。
    from app.core.database import utcnow
    from app.modules.identity.authorization import fixed_college_actions
    from app.modules.identity.grant_scope import (
        LIMITED_ACTIONS,
        active_grants,
        is_whole_college,
        resource_definition,
    )

    service = CampusService(db)
    college = service._authorize(actor, college_id, action, write=write,
                                 allow_restricted=action in LIMITED_ACTIONS)
    grants = active_grants(service.repo.grants(actor.id, college_id=college_id, lock=write),
                           college_id, utcnow(), action)
    unrestricted = action in fixed_college_actions(db, actor.id, college_id) or any(is_whole_college(row) for row in grants)

    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(child) for key, child in value.items()})
        if isinstance(value, list):
            return tuple(freeze(child) for child in value)
        return value

    clauses = tuple(freeze(resource_definition(row)) for row in grants if not is_whole_college(row))
    return ResourceScope(actor.id, college.id, action, college.authorization_revision, unrestricted, clauses)
