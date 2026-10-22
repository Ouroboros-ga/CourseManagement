"""解析预算（A4）：超限表格必须早停，且不得重复走兜底解析链。

生产单 worker 的 MemoryMax=384M，全量物化一张 104 万行的工作表会直接打死整个 API。
"""

import io

import pytest
from app.common.parsing.xlsx_tabular import (
    TableTooLarge,
    read_any_matrix,
    read_tabular_rows,
)
from openpyxl import Workbook


def _xlsx(rows: int, columns: int = 2) -> bytes:
    book = Workbook()
    ws = book.active
    ws.append(["学号", "姓名", "第三列", "第四列"][:columns])
    for index in range(rows):
        ws.append([f"2024{index:05d}", f"学生{index}"][:columns])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_rows_within_budget_are_read_normally():
    rows = read_tabular_rows(_xlsx(3), include_source=True)
    assert [r["学号"] for r in rows] == ["202400000", "202400001", "202400002"]
    assert [r["_source_row"] for r in rows] == ["2", "3", "4"]


def test_row_budget_stops_early_with_a_clear_message():
    with pytest.raises(TableTooLarge, match="超出解析上限"):
        read_tabular_rows(_xlsx(50), max_rows=10)


def test_column_budget_rejects_wide_sheets():
    with pytest.raises(TableTooLarge, match="列数"):
        read_tabular_rows(_xlsx(2, columns=4), max_columns=3)


def test_oversized_sheet_does_not_replay_the_fallback_chain(monkeypatch):
    """超限必须是 TableTooLarge 而不是被兜底链当成"格式不对"再解析一遍。"""
    import app.common.parsing.xlsx_tabular as mod

    calls = []
    real = mod.read_any_matrix

    def spy(data, **kwargs):
        calls.append(data)
        return real(data, **kwargs)

    monkeypatch.setattr(mod, "read_any_matrix", spy)
    with pytest.raises(TableTooLarge):
        mod.read_tabular_rows(_xlsx(30), max_rows=5)
    assert calls == []


def test_read_any_matrix_is_also_bounded():
    with pytest.raises(TableTooLarge):
        read_any_matrix(_xlsx(40), max_rows=8)


def test_csv_budget_is_enforced():
    payload = "学号,姓名\n" + "\n".join(f"{202400000+i},学生{i}" for i in range(60))
    with pytest.raises(TableTooLarge):
        read_any_matrix(payload.encode("utf-8-sig"), max_rows=20)


def test_blank_rows_do_not_consume_the_row_budget():
    book = Workbook()
    ws = book.active
    ws.append(["学号", "姓名"])
    for _ in range(20):
        ws.append([None, None])
    ws.append(["202400001", "保留行"])
    stream = io.BytesIO()
    book.save(stream)
    rows = read_tabular_rows(stream.getvalue(), max_rows=5)
    assert [r["学号"] for r in rows] == ["202400001"]
