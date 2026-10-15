"""个人修改仅保存个人聚合；不更新正式课表、名单、任务或报表修订。"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, ErrorCode, NotFoundError
from app.modules.academic.publication_service import MyAcademicSourceService
from app.modules.organization.service import atomic_write, validated
from app.modules.timetable.models import PersonalTimetable
from app.modules.timetable.repository import PersonalTimetableRepository
from app.modules.timetable.schemas import EntryCreate, EntryUpdate, EntryValues

EDIT_FIELDS = set(EntryValues.model_fields)


class PersonalTimetableService:
    def __init__(self, db: Session, user_id: int):
        self.db, self.user_id = db, user_id
        self.repo = PersonalTimetableRepository(db)

    def _dto(self, semester_id: int, row, *, status="NOT_INITIALIZED"):
        entries = [{**entry, "exceptions": list(
            (row.occurrence_exceptions or {}).get(entry["id"], {}).values())}
            for entry in row.entries] if row else []
        return {
            "semester_id": str(semester_id),
            "status": "INITIALIZED" if row else status,
            "source_revision": row.source_revision if row else None,
            "sources": row.sources if row else [],
            "entries": entries,
            "current_version": row.current_version if row else None,
        }

    def get(self, semester_id: int):
        student = self.repo.student(self.user_id)
        return self._dto(semester_id, self.repo.get(student.id, semester_id))

    def semesters(self):
        student = self.repo.student(self.user_id)
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "initialized": version is not None,
                "current_version": version,
            }
            for row, version in self.repo.semesters(student.id)
        ]

    @atomic_write
    def initialize(self, semester_id: int):
        student = self.repo.student(self.user_id, lock=True)
        row = self.repo.get(student.id, semester_id, lock=True)
        if row:
            result = self._dto(semester_id, row)
            self.db.commit()
            return result
        source = MyAcademicSourceService(self.db, self.user_id).initialize(semester_id)
        if source["status"] == "NOT_PUBLISHED":
            self.db.commit()
            return self._dto(semester_id, None, status="NOT_PUBLISHED")
        row = PersonalTimetable(
            student_id=student.id,
            semester_id=semester_id,
            source_revision=source["source_revision"],
            sources=source["sources"],
            entries=[{**entry, "id": str(uuid4()), "note": ""} for entry in source["entries"]],
        )
        self.db.add(row)
        self.db.flush()
        result = self._dto(semester_id, row)
        self.db.commit()
        return result

    def _editable(self, semester_id: int, version: int):
        student = self.repo.student(self.user_id, lock=True)
        row = self.repo.get(student.id, semester_id, lock=True)
        if row is None:
            raise ConflictError(ErrorCode.STATE_CONFLICT, "请先初始化本学期个人课表")
        if row.current_version != version:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "个人课表已在其他设备保存，请刷新后重试"
            )
        return row

    def _save(self, row, entries: list):
        row.entries = entries
        row.current_version += 1
        self.db.flush()
        result = self._dto(row.semester_id, row)
        self.db.commit()
        return result

    @atomic_write
    def create_entry(self, semester_id: int, data):
        body = validated(EntryCreate, data)
        row = self._editable(semester_id, body.current_version)
        if len(row.entries) >= 500:
            raise AppError(ErrorCode.VALIDATION_ERROR, "个人课表最多保存 500 条课程", 422)
        entry = {
            **body.model_dump(mode="json", exclude={"current_version"}),
            "id": str(uuid4()),
            "source_schedule_id": None,
            "teaching_class_id": None,
            "college_id": None,
            "class_name": None,
            "start_period": None,
            "end_period": None,
        }
        return self._save(row, [*row.entries, entry])

    @atomic_write
    def update_entry(self, semester_id: int, entry_id: str, data):
        body = validated(EntryUpdate, data)
        row = self._editable(semester_id, body.current_version)
        found = next((entry for entry in row.entries if entry["id"] == entry_id), None)
        if found is None:
            raise NotFoundError("个人课程不存在")
        if {"week_nos", "weekday", "occurrence_dates"} & body.model_fields_set and (
            (row.occurrence_exceptions or {}).get(entry_id)
        ):
            raise ConflictError(message="该课程存在单次修改，请先撤销单次修改再调整重复日期规则")
        values = {key: found.get(key) for key in EDIT_FIELDS}
        if {
            "week_nos",
            "weekday",
        } & body.model_fields_set and "occurrence_dates" not in body.model_fields_set:
            values["occurrence_dates"] = None
        values.update(body.model_dump(exclude_unset=True, exclude={"current_version"}))
        updated = validated(EntryValues, values).model_dump(mode="json")
        return self._save(
            row,
            [{**entry, **updated} if entry["id"] == entry_id else entry for entry in row.entries],
        )

    @atomic_write
    def delete_entry(self, semester_id: int, entry_id: str, current_version: int):
        row = self._editable(semester_id, current_version)
        entries = [entry for entry in row.entries if entry["id"] != entry_id]
        if len(entries) == len(row.entries):
            raise NotFoundError("个人课程不存在")
        if len(row.deleted_entries or []) >= 500:
            raise ConflictError(message="可恢复删除记录已达500条，请先恢复所需条目")
        found = next(entry for entry in row.entries if entry["id"] == entry_id)
        from app.core.database import utcnow
        row.deleted_entries = [*(row.deleted_entries or []),
            {"entry": found, "deleted_at": utcnow().isoformat() + "Z"}]
        return self._save(row, entries)

    def deleted(self, semester_id):
        student = self.repo.student(self.user_id)
        row = self.repo.get(student.id, semester_id)
        return {"current_version": row.current_version if row else None,
                "items": row.deleted_entries or [] if row else []}

    @atomic_write
    def restore(self, semester_id, entry_id, version):
        row = self._editable(semester_id, version)
        deleted = next((item for item in row.deleted_entries or []
                        if item["entry"]["id"] == entry_id), None)
        if deleted is None:
            raise NotFoundError("可恢复课程不存在")
        if len(row.entries) >= 500 or any(entry["id"] == entry_id for entry in row.entries):
            raise ConflictError(message="课程容量已满或条目已存在")
        row.deleted_entries = [item for item in row.deleted_entries if item != deleted]
        return self._save(row, [*row.entries, deleted["entry"]])

    @atomic_write
    def set_exception(self, semester_id, entry_id, day, data):
        from app.modules.timetable.occurrences import save_exception
        row = self._editable(semester_id, data["current_version"])
        save_exception(self.db, row, entry_id, day, data)
        return self._save(row, row.entries)

    @atomic_write
    def remove_exception(self, semester_id, entry_id, day, version):
        row = self._editable(semester_id, version)
        if not any(entry["id"] == entry_id for entry in row.entries):
            raise NotFoundError("个人课程不存在")
        exceptions = {key: dict(values) for key, values in (row.occurrence_exceptions or {}).items()}
        values = exceptions.get(entry_id, {})
        if day.isoformat() not in values:
            raise NotFoundError("单次修改不存在")
        del values[day.isoformat()]
        row.occurrence_exceptions = exceptions
        return self._save(row, row.entries)
