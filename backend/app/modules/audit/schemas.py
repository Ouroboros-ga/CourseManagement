"""审计只读接口的数据边界与安全投影。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

SAFE_FIELDS = frozenset({
    "status", "lock_version", "student_id", "semester_id", "teaching_class_id",
    "course_id", "schedule_id", "task_id", "assignment_id", "volunteer_user_id",
    "weekday", "start_period", "end_period", "week_no", "enabled",
    "role_codes", "permission_codes", "expected_count", "present_count",
    "roles", "code", "reviewed_by", "reviewed_at", "result",
    "absent_count", "late_count", "leave_count", "review_status",
    "attendance_type", "classroom", "class_name", "course_name",
})
ID_FIELDS = frozenset({
    "student_id", "semester_id", "teaching_class_id", "course_id", "schedule_id",
    "task_id", "assignment_id", "volunteer_user_id", "reviewed_by",
})
SCALAR_TYPES = (str, int, float, bool)


def safe_snapshot(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = {}
    for key, raw in value.items():
        if key not in SAFE_FIELDS:
            continue
        if raw is None:
            result[key] = None
        elif key in ID_FIELDS and isinstance(raw, (str, int)):
            result[key] = str(raw)
        elif isinstance(raw, SCALAR_TYPES):
            result[key] = raw
        elif key in ("role_codes", "permission_codes", "roles") and isinstance(raw, list):
            result[key] = [item for item in raw if isinstance(item, str)][:100]
    return result


def validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is not None:
        start = start.astimezone(UTC).replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.astimezone(UTC).replace(tzinfo=None)
    if end < start:
        raise ValueError("结束时间不得早于开始时间")
    if end - start > timedelta(days=31):
        raise ValueError("审计查询时间窗口最多 31 天")
