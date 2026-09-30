"""将日历日期解析为实际执行的教学周与教学星期。"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.modules.academic.models import OverrideType


class TeachingDayOverride(Protocol):
    override_type: str
    source_teaching_week: int | None
    source_teaching_weekday: int | None


def resolve_teaching_day(
    first_monday: date,
    on_date: date,
    override: TeachingDayOverride | None = None,
) -> tuple[int, int] | None:
    """STOP 无教学日；MAKEUP 取来源周/星期，旧记录缺来源周时沿用实际周。"""
    if override is not None and override.override_type == OverrideType.STOP.value:
        return None

    actual_week = (on_date - first_monday).days // 7 + 1
    if override is not None and override.override_type == OverrideType.MAKEUP.value:
        if override.source_teaching_weekday is None:
            return None  # 兼容旧生成行为：来源星期残缺的补课记录不可猜测。
        return (
            override.source_teaching_week or actual_week,
            override.source_teaching_weekday,
        )
    return actual_week, on_date.isoweekday()
