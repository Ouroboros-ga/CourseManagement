"""复用一次审核事务，管理读取与改判授权均保持同一学院。"""

from sqlalchemy.orm import Session

from app.core.exceptions import PermissionDeniedError
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.objection import permissions as perms
from app.modules.objection.repository import ObjectionRepository
from app.modules.objection.service import ObjectionService
from app.modules.organization.service import CampusService


class ScopedObjectionService(ObjectionService):
    def __init__(self, db: Session, actor: CurrentUser, college_id: int):
        super().__init__(db)
        self.actor, self.college_id = actor, college_id

    def _require(self, actor_user_id: int, code: str) -> set[str]:
        if actor_user_id != self.actor.id or code not in {
            "objection.read",
            "objection.final_review",
        }:
            raise PermissionDeniedError()
        scope = resolve_scope(
            self._session, self.actor, self.college_id, code, write=code == "objection.final_review"
        )
        self._repo = ObjectionRepository(self._session, scope)
        return set(
            CampusService(self._session).capabilities(self.actor, self.college_id)["capabilities"]
        )

    def _lock_actor(self, actor_user_id: int) -> set[str]:
        return self._require(actor_user_id, "objection.read")

    def _read_scope(self, actor_user_id: int, permissions: set[str]):
        if actor_user_id != self.actor.id or self._repo.scope is None:
            raise PermissionDeniedError()
        return perms.ObjectionScope.MANAGE, None

    def _legacy_manage_gate(self):
        if self._repo.scope is None or self._repo.scope.action != "objection.final_review":
            raise PermissionDeniedError()
