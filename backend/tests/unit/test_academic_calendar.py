"""校历覆盖在实际日期与来源教学日之间的映射。"""

from datetime import date
from types import SimpleNamespace

import pytest
from app.modules.academic.calendar import resolve_teaching_day
from app.modules.academic.schemas import CalendarOverrideCreateRequest
from pydantic import ValidationError

FIRST_MONDAY = date(2026, 9, 14)


@pytest.mark.parametrize(
    ("actual_date", "override", "expected"),
    [
        (date(2026, 9, 14), None, (1, 1)),
        (date(2026, 9, 20), SimpleNamespace(override_type="MAKEUP", source_teaching_week=2,
                                            source_teaching_weekday=5), (2, 5)),
        (date(2026, 10, 10), SimpleNamespace(override_type="MAKEUP", source_teaching_week=3,
                                             source_teaching_weekday=5), (3, 5)),
        (date(2026, 9, 20), SimpleNamespace(override_type="MAKEUP", source_teaching_week=None,
                                            source_teaching_weekday=5), (1, 5)),
    ],
)
def test_resolve_teaching_day_uses_source_week_when_supplied(actual_date, override, expected):
    assert resolve_teaching_day(FIRST_MONDAY, actual_date, override) == expected


@pytest.mark.parametrize("day", range(1, 8))
def test_national_holiday_stop_has_no_teaching_day(day):
    override = SimpleNamespace(override_type="STOP", source_teaching_week=None,
                               source_teaching_weekday=None)
    assert resolve_teaching_day(FIRST_MONDAY, date(2026, 10, day), override) is None


def test_stop_rejects_source_fields():
    with pytest.raises(ValidationError):
        CalendarOverrideCreateRequest(
            date=date(2026, 10, 1), override_type="STOP",
            source_teaching_week=3, source_teaching_weekday=5,
        )


def test_legacy_makeup_without_source_weekday_is_not_guessed():
    override = SimpleNamespace(override_type="MAKEUP", source_teaching_week=None,
                               source_teaching_weekday=None)
    assert resolve_teaching_day(FIRST_MONDAY, date(2026, 9, 20), override) is None


@pytest.mark.parametrize("week", [0, -1])
def test_source_week_must_be_positive(week):
    with pytest.raises(ValidationError):
        CalendarOverrideCreateRequest(
            date=date(2026, 9, 20), override_type="MAKEUP",
            source_teaching_week=week, source_teaching_weekday=5,
        )
