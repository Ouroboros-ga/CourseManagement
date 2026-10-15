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

    def correct_archived(self, actor, record_id, body, request_id=None):
        from sqlalchemy import select
        from app.core.exceptions import ConflictError, NotFoundError
        from app.modules.academic.models import Semester
        from app.modules.identity.repository import IdentityRepository
        from app.modules.inspection.models import InspectionTask
        roles = set(IdentityRepository(self._session).list_role_codes(actor.id))
        if not roles & {"TEACHER_ADMIN", "SUPER_ADMIN"}:
            raise PermissionDeniedError("归档更正仅允许有该记录更正权限的教师或超管")
        self._require(actor.id, "attendance.correct")
        record = self._repo.get_record_for_update(record_id)
        if record is None:
            raise NotFoundError("考勤记录不存在")
        sid = self._session.scalar(select(InspectionTask.semester_id).where(InspectionTask.id == record.task_id))
        status = self._session.scalar(select(Semester.status).where(Semester.id == sid).with_for_update(read=True))
        if status != "ARCHIVED" or not body.reason.strip():
            raise ConflictError(message="归档更正须针对已归档学期，并填写更正依据")
        self._archive_correction = True
        try:
            return self.correct(actor, record_id, body, request_id)
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._archive_correction = False
