"""Personal date exceptions never call the formal timetable/time resolver."""

from datetime import date

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.models import Semester
from app.modules.organization.service import validated
from app.modules.timetable.schemas import EntryValues, OccurrenceEdit


def is_occurrence(semester, entry, day):
    if entry.get("occurrence_dates") is not None:
        return day.isoformat() in entry["occurrence_dates"]
    week = (day - semester.first_monday).days // 7 + 1
    return day.isoweekday() == entry["weekday"] and week in entry["week_nos"]


def save_exception(db, row, entry_id: str, day: date, data):
    body = validated(OccurrenceEdit, data)
    entry = next((entry for entry in row.entries if entry["id"] == entry_id), None)
    semester = db.get(Semester, row.semester_id)
    if entry is None:
        raise NotFoundError("个人课程不存在")
    if not semester.start_date <= day <= semester.end_date or not is_occurrence(
        semester, entry, day
    ):
        raise ConflictError(message="指定日期不属于这条个人课程")
    previous = (row.occurrence_exceptions or {}).get(entry_id, {}).get(day.isoformat())
    target = body.target_date or (date.fromisoformat(previous["target_date"]) if previous else day)
    if not semester.start_date <= target <= semester.end_date:
        raise ConflictError(message="单次课程日期须在本学期内")
    overrides = {k: dict(v) for k, v in (row.occurrence_exceptions or {}).items()}
    values = overrides.setdefault(entry_id, {})
    previous = values.get(day.isoformat())
    content = (
        dict(previous["values"])
        if previous
        else {key: value for key, value in entry.items() if key in EntryValues.model_fields}
    )
    content.update(
        body.model_dump(exclude_unset=True, exclude={"current_version", "cancelled", "target_date"})
    )
    content = validated(EntryValues, content).model_dump(mode="json")
    if not previous and sum(len(v) for v in overrides.values()) >= 2000:
        raise ConflictError(message="个人课表单次修改最多保存2000条")
    values[day.isoformat()] = {
        "date": day.isoformat(),
        "target_date": target.isoformat(),
        "cancelled": body.cancelled,
        "values": content,
    }
    row.occurrence_exceptions = overrides
