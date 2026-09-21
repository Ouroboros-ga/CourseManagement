"""时间标准化解析单测（移植自遗留 test_normalize，保留原边界）。"""

from __future__ import annotations

import pytest
from app.common.parsing.time_slots import (
    DEFAULT_SLOT_MAPPING,
    parse_period,
    parse_weekday,
    parse_weeks,
)


def test_odd_weeks():
    assert parse_weeks("1-7单周", 20) == [1, 3, 5, 7]


@pytest.mark.parametrize("text", ["0-3", "21", "8-1", "随便一周"])
def test_invalid_weeks(text):
    with pytest.raises(ValueError):
        parse_weeks(text, 20)


def test_weeks_range_and_list():
    assert parse_weeks("1-16", 16) == list(range(1, 17))
    assert parse_weeks("1,3,5,8", 16) == [1, 3, 5, 8]
    assert parse_weeks("第1-8周", 16) == list(range(1, 9))


def test_weeks_even():
    assert parse_weeks("2-16双周", 16) == [2, 4, 6, 8, 10, 12, 14, 16]
    assert parse_weeks("1-15单周", 16) == [1, 3, 5, 7, 9, 11, 13, 15]


def test_weeks_spaces_and_fullwidth():
    assert parse_weeks(" 1 - 4 ", 16) == [1, 2, 3, 4]
    assert parse_weeks("1，3，5", 16) == [1, 3, 5]
    assert parse_weeks("1、3、5", 16) == [1, 3, 5]
    assert parse_weeks("1～4", 16) == [1, 2, 3, 4]


def test_weeks_sorted_unique():
    assert parse_weeks("8,1,3", 16) == [1, 3, 8]
    assert parse_weeks("1-3,2", 16) == [1, 2, 3]
    assert parse_weeks("1-4,6,8-10双周", 16) == [1, 2, 3, 4, 6, 8, 10]


@pytest.mark.parametrize(
    "text",
    ["", "   ", "1,,3", "1-17", "0", "0-3", "1-4,99", "2-2单周", "4单周", "=A1"],
)
def test_weeks_invalid_extra(text):
    with pytest.raises(ValueError):
        parse_weeks(text, 16)


def test_weeks_int_input():
    assert parse_weeks(5, 16) == [5]
    with pytest.raises(ValueError):
        parse_weeks(0, 16)
    with pytest.raises(ValueError):
        parse_weeks(17, 16)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        (7, 7),
        ("1", 1),
        ("周一", 1),
        ("周三", 3),
        ("周日", 7),
        ("周天", 7),
        ("星期一", 1),
        ("星期五", 5),
        ("星期天", 7),
        ("  周五  ", 5),
        ("三", 3),
    ],
)
def test_weekday_valid(value, expected):
    assert parse_weekday(value) == expected


@pytest.mark.parametrize("value", [0, 8, "0", "8", "周八", "Monday", "", "随便"])
def test_weekday_invalid(value):
    with pytest.raises(ValueError):
        parse_weekday(value)


def test_period_small_sections():
    assert parse_period("1-2") == [1]
    assert parse_period("3-4") == [2]
    assert parse_period("5-6") == [3]
    assert parse_period("7-8") == [4]
    assert parse_period("9-10") == [5]
    assert parse_period("1") == [1]
    assert parse_period("2") == [1]
    assert parse_period("3") == [2]
    assert parse_period("第1-2节") == [1]
    assert parse_period("5-6节") == [3]
    assert parse_period("1-6") == [1, 2, 3]
    assert parse_period(1) == [1]
    assert parse_period(10) == [5]


def test_period_custom_mapping():
    custom = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2}
    assert parse_period("1-3", slot_mapping=custom) == [1]
    assert parse_period("1-5", slot_mapping=custom) == [1, 2]


@pytest.mark.parametrize("value", ["", "11", "5-1", "随便", "=A1+2", "1,,2"])
def test_period_invalid(value):
    with pytest.raises(ValueError):
        parse_period(value)


def test_default_slot_mapping_contract():
    assert DEFAULT_SLOT_MAPPING == {
        1: 1,
        2: 1,
        3: 2,
        4: 2,
        5: 3,
        6: 3,
        7: 4,
        8: 4,
        9: 5,
        10: 5,
    }
