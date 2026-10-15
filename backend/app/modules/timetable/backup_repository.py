"""Backup persistence; identity and student locks serialize same-student uploads."""

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester
from app.modules.identity.role_scope import business_today
from app.modules.timetable.models import TimetableBackup
from app.modules.timetable.repository import PersonalTimetableRepository


class TimetableBackupRepository(PersonalTimetableRepository):
    def semester(self, semester_id=None):
        if semester_id is not None:
            row = self.db.get(Semester, semester_id)
            if row is None:
                raise NotFoundError("学期不存在")
            return row
        today = business_today()
        active = list(self.db.scalars(select(Semester).where(Semester.status == "ACTIVE")))
        current = [row for row in active if row.start_date <= today <= row.end_date]
        choices = current or active
        if len(choices) != 1:
            raise ConflictError(message="无法唯一确定当前学期，请指定semester_id")
        return choices[0]

    def backup(self, student_id, semester_id, *, lock=False):
        stmt = select(TimetableBackup).where(
            TimetableBackup.student_id == student_id, TimetableBackup.semester_id == semester_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return self.db.scalar(stmt.execution_options(populate_existing=True))
