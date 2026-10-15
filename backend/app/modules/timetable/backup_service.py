"""Adapt published personal sources; keep display backups out of formal business."""

import hashlib
import json
from collections import defaultdict
from datetime import date

from app.core.database import utcnow
from app.core.exceptions import ConflictError
from app.modules.academic.models import AdministrativeClass
from app.modules.academic.publication_service import MyAcademicSourceService
from app.modules.identity.role_scope import business_today
from app.modules.organization.service import atomic_write, validated
from app.modules.timetable.backup_repository import TimetableBackupRepository
from app.modules.timetable.backup_schemas import BackupWrite
from app.modules.timetable.models import TimetableBackup


class TimetableBackupService:
    def __init__(self, db, user_id):
        self.db, self.user_id = db, user_id
        self.repo = TimetableBackupRepository(db)

    @staticmethod
    def semester_dto(semester):
        return {
            "id": str(semester.id),
            "name": semester.name,
            "total_weeks": semester.total_weeks,
            "first_monday": str(semester.first_monday),
            "current_week": (business_today() - semester.first_monday).days // 7 + 1,
        }

    def _dto(self, semester, row):
        return {
            "semester_id": str(semester.id),
            "semester": self.semester_dto(semester),
            "has_backup": row is not None,
            "backup_version": row.backup_version if row else None,
            "updated_at": row.updated_at.isoformat() + "Z" if row else None,
            "schedule_data": row.schedule_data if row else [],
        }

    def get(self, semester_id=None):
        student = self.repo.student(self.user_id)
        semester = self.repo.semester(semester_id)
        return self._dto(semester, self.repo.backup(student.id, semester.id))

    @atomic_write
    def save(self, semester_id, schedule_data):
        body = validated(BackupWrite, {"semester_id": semester_id, "schedule_data": schedule_data})
        student = self.repo.student(self.user_id, lock=True)
        semester = self.repo.semester(body.semester_id)
        row = self.repo.backup(student.id, semester.id, lock=True)
        content = [item.model_dump(mode="json", exclude_unset=True) for item in body.schedule_data]
        if row is None:
            row = TimetableBackup(
                student_id=student.id,
                semester_id=semester.id,
                schedule_data=content,
                backup_version=1,
            )
            self.db.add(row)
        else:
            row.schedule_data = content
            row.backup_version += 1
            row.updated_at = utcnow()
        self.db.flush()
        result = self._dto(semester, row)
        self.db.commit()
        return result

    def class_timetable(self, semester_id=None):
        student = self.repo.student(self.user_id)
        semester = self.repo.semester(semester_id)
        source = MyAcademicSourceService(self.db, self.user_id).initialize(semester.id)
        if source["status"] == "NOT_PUBLISHED":
            raise ConflictError(message="本学期教务课表尚未正式发布")
        administrative = (
            self.db.get(AdministrativeClass, student.administrative_class_id)
            if student.administrative_class_id
            else None
        )
        items = []
        for entry in source["entries"]:
            dates = entry.get("occurrence_dates")
            by_weekday = defaultdict(list)
            if dates is not None:
                for value in dates:
                    day = date.fromisoformat(value)
                    by_weekday[day.isoweekday()].append(value)
            else:
                by_weekday[entry["weekday"]] = None
            for weekday, actual_dates in sorted(by_weekday.items()):
                weeks = (
                    sorted(
                        {
                            (date.fromisoformat(day) - semester.first_monday).days // 7 + 1
                            for day in actual_dates
                        }
                    )
                    if actual_dates is not None
                    else entry["week_nos"]
                )
                # Different time segments of one official schedule must keep distinct display IDs.
                key = [entry["source_schedule_id"], entry["start_time"], entry["end_time"], weekday]
                suffix = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20]
                items.append(
                    {
                        "course_id": "official-class-" + entry["teaching_class_id"],
                        "scheme_id": "official-" + suffix,
                        "course_name": entry["course_name"],
                        "course_code": "",
                        "teacher_name": entry.get("teacher") or "",
                        "classroom": entry.get("classroom") or "",
                        "is_custom": False,
                        "weekday": weekday,
                        "start_period": entry.get("start_period"),
                        "end_period": entry.get("end_period"),
                        "weeks": weeks,
                        "note": "",
                        "occurrence_dates": actual_dates,
                        "start_time": entry["start_time"],
                        "end_time": entry["end_time"],
                    }
                )
        return {
            "semester": self.semester_dto(semester),
            "class_name": administrative.class_name if administrative else "",
            "source_revision": source["source_revision"],
            "items": items,
        }
