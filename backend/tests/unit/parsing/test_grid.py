"""方格课表解析单测（移植自遗留 test_school_grid，snapshot 展开改用 expand_grid_rows）。"""

from __future__ import annotations

from app.common.parsing.dto import make_course_key
from app.common.parsing.grid import (
    SCHOOL_SLOT_MAPPING,
    expand_grid_rows,
    extract_class_id,
    grid_to_rows,
    load_xlsx_grid,
    normalize_weeks,
    parse_cell_blocks,
    split_weeks_period,
)
from app.common.parsing.time_slots import parse_period, parse_weeks

CELL_SINGLE = "PLC技术与工控组态\r\n◇1-11周(1-4节)◇教学楼14-402◇黄朝阳◇选课人数：32"
CELL_ODD = "液压与气压传动\r\n◇1-13周(单)(1-2节)◇教学楼13-403◇郑红梅◇选课人数：32"
CELL_DOUBLE_BLOCK = (
    "机械设计B\r\n◇1-10周(3-4节)◇教学楼13-203◇徐静◇选课人数：32\r\n"
    "机械设计B\r\n◇11-14周(3-4节)◇教学楼14-406◇徐静◇选课人数：16"
)
CELL_EVEN = "机械工程控制基础\r\n◇2-14周(双)(3-4节)◇教学楼14-110◇何剑春◇选课人数：32"
CELL_SPAN = "液压与气压传动\r\n◇14-15周(5-8节)◇教学楼14-406◇郑红梅◇选课人数：32"


def test_parse_single_block():
    (b,) = parse_cell_blocks(CELL_SINGLE)
    assert b["course_name"] == "PLC技术与工控组态"
    assert b["weeks"] == "1-11周"
    assert b["period"] == "1-4节"


def test_odd_even_normalize():
    assert normalize_weeks("1-13周(单)") == "1-13周单周"
    assert normalize_weeks("2-14周(双)") == "2-14周双周"
    (b,) = parse_cell_blocks(CELL_ODD)
    assert b["weeks"] == "1-13周单周"
    (b2,) = parse_cell_blocks(CELL_EVEN)
    assert b2["weeks"] == "2-14周双周"


def test_double_block_cell():
    blocks = parse_cell_blocks(CELL_DOUBLE_BLOCK)
    assert len(blocks) == 2
    assert [b["weeks"] for b in blocks] == ["1-10周", "11-14周"]


def test_split_weeks_period():
    assert split_weeks_period("1-11周(1-4节)") == ("1-11周", "1-4节")
    assert split_weeks_period("14-15周(5-8节)") == ("14-15周", "5-8节")


def test_extract_class_id():
    assert extract_class_id(["2026-2027学年第1学期", "", "机电2401课表"]) == "机电2401"
    assert extract_class_id(["无关表头"]) == ""


def test_converted_strings_pass_template_parsers_17():
    cells = [
        ("周二", CELL_SINGLE),
        ("周五", CELL_ODD),
        ("周一", CELL_DOUBLE_BLOCK),
        ("周五", CELL_EVEN),
        ("周四", CELL_SPAN),
    ]
    rows = grid_to_rows(cells)
    assert len(rows) == 6
    for r in rows:
        assert parse_weeks(r["weeks"], 17)
        assert parse_period(r["period"])
    span = next(r for r in rows if r["weeks"] == "14-15周")
    assert parse_period(span["period"]) == [3, 4]


def test_evening_periods_need_school_mapping():
    assert parse_period("11-12节", SCHOOL_SLOT_MAPPING) == [6]
    assert parse_period("10-11节", SCHOOL_SLOT_MAPPING) == [5, 6]
    assert parse_period("9-11节", SCHOOL_SLOT_MAPPING) == [5, 6]


def test_xlsx_grid_same_layout():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet0"
    ws.append(["2026-2027学年第1学期", "", "", "机电2401课表"])
    ws.append(["时间段", "节次", "星期一", "星期二"])
    ws.append(
        [
            "上午",
            "1",
            "",
            "PLC技术与工控组态\r\n◇1-11周(1-4节)◇教学楼14-402◇黄朝阳◇选课人数：32",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    class_id, rows = load_xlsx_grid(buf.getvalue())
    assert class_id == "机电2401"
    assert len(rows) == 1
    assert rows[0]["weeks"] == "1-11周" and rows[0]["period"] == "1-4节"


def test_expand_grid_rows_expands_evening_17():
    rows = [
        {
            "course_id": "Cx",
            "class_id": "A",
            "course_name": "课",
            "weeks": "1-2周",
            "weekday": "周二",
            "period": "11-12节",
            "location": "",
            "teacher": "",
            "count": "1",
        },
    ]
    occ = expand_grid_rows(rows, 17, dict(SCHOOL_SLOT_MAPPING))
    assert len(occ) == 2  # 2 周 × 大节 6
    assert occ[0].week_no == 1
    assert occ[0].weekday == 2
    assert occ[0].start_period == 6


def test_expand_course_key_is_order_independent():
    base = {
        "class_id": "A",
        "course_name": "课",
        "weeks": "1-3周",
        "weekday": "周二",
        "period": "1-2节",
        "location": "楼1",
    }
    one = expand_grid_rows([{**base, "course_id": "C001"}], 16)
    # 同一门课 3 周 × 大节 1 → 3 个占用，共享同一 course_key
    assert len(one) == 3
    assert len({c.course_key for c in one}) == 1
    # 稳定 key 与 make_course_key 一致
    assert one[0].course_key == make_course_key("A", "课", parse_weeks("1-3周", 16), 2, [1], "楼1")
