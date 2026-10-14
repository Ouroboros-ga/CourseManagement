"""重用考勤认定事务，范围由完整动作＋学院解析后显式交给 Repository。"""

from sqlalchemy.orm import Session

from app.core.exceptions import PermissionDeniedError
from app.modules.attendance.repository import AttendanceRepository
from app.modules.attendance.service import AttendanceService
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser


class ScopedAttendanceService(AttendanceService):
    def __init__(self, db: Session, actor: CurrentUser, college_id: int):
        super().__init__(db)
        self.actor, self.college_id = actor, college_id

    def _require(self, actor_user_id: int, code: str) -> None:
        if actor_user_id != self.actor.id:
            raise PermissionDeniedError()
        scope = resolve_scope(
            self._session, self.actor, self.college_id, code, write=code == "attendance.correct"
        )
        self._repo = AttendanceRepository(self._session, scope)

    def _legacy_manage_gate(self):
        # 本类所有公开操作先调用 _require，且记录在带范围 SQL 中读取。
        if self._repo.scope is None:
            raise PermissionDeniedError("尚未解析考勤范围")

    def _can_manage(self, actor):
        return actor.id == self.actor.id and self._repo.scope is not None
