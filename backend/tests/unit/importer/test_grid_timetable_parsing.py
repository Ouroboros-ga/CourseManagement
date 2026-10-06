"""Unit tests for grid timetable parsing and class name normalization."""

import pytest

from app.common.parsing.grid import load_grid, normalize_class_name, SCHOOL_SLOT_MAPPING
from app.common.parsing.time_slots import parse_period, parse_weekday, parse_weeks


def test_normalize_class_name():
    assert normalize_class_name("数据科学2401") == "数科2401"
    assert normalize_class_name("数科2401") == "数科2401"
    assert normalize_class_name("计算机类2601") == "计算机2601"
    assert normalize_class_name("机械电子工程2401") == "机电2401"
    assert normalize_class_name("机电2401") == "机电2401"
    assert normalize_class_name("机械设计制造及其自动化2501") == "机自2501"


def test_school_slot_mapping():
    # 1-2节 -> 大节 1
    slots1 = parse_period("1-2节", slot_mapping=SCHOOL_SLOT_MAPPING)
    assert slots1 == [1]

    # 3-4节 -> 大节 2
    slots2 = parse_period("3-4节", slot_mapping=SCHOOL_SLOT_MAPPING)
    assert slots2 == [2]

    # 5-6节 -> 大节 3
    slots3 = parse_period("5-6节", slot_mapping=SCHOOL_SLOT_MAPPING)
    assert slots3 == [3]

    # 10-11节 -> 大节 5, 6
    slots4 = parse_period("10-11节", slot_mapping=SCHOOL_SLOT_MAPPING)
    assert slots4 == [5, 6]
