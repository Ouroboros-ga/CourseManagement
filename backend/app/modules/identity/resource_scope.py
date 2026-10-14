"""动作与学院完整绑定的不可变查询范围；不是客户端传入的学院列表。"""

from dataclasses import dataclass

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
    college = CampusService(db)._authorize(actor, college_id, action, write=write)
    return ResourceScope(actor.id, college.id, action, college.authorization_revision)
