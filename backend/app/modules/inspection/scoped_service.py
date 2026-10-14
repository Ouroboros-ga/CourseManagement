"""Reuse inspection transactions with one explicitly selected college, never a grant union."""

from sqlalchemy import select

from app.core.exceptions import PermissionDeniedError
from app.modules.identity.authorization import CAMPUS_ACTIONS
from app.modules.identity.resource_scope import resolve_scope
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.service import InspectionService
from app.modules.organization.service import CampusService


class ScopedInspectionService(InspectionService):
    def __init__(self, db, actor, cid):
        super().__init__(db)
        self.actor, self.cid = actor, cid

    def _require(self, actor_user_id, code):
        if actor_user_id != self.actor.id or code not in CAMPUS_ACTIONS:
            raise PermissionDeniedError()
        resolve_scope(self._session, self.actor, self.cid, code, write=not code.endswith(".read"))
        self._repo.college_ids = frozenset({self.cid})
        self._repo.deadline_scope_id = self.cid
        return set(CampusService(self._session).capabilities(self.actor, self.cid)["capabilities"])

    def _scope_filter(self, actor, action="inspection.read"):
        if actor.id != self.actor.id:
            raise PermissionDeniedError()
        resolve_scope(self._session, actor, self.cid, action)
        return select(InspectionTask).where(InspectionTask.college_id == self.cid)
