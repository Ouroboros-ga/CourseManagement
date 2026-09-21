"""表格式 xlsx 读取：把首个工作表按表头行读成 list[dict[str,str]]（技术方案 19）。

导入模板统一冻结为**表格式**（每行一条记录、首行为表头），与"方格课表"
(:mod:`app.common.parsing.grid`) 互补：方格用于贴合学校原始周课表导出，表格式
用于名单 / 志愿者资格 / 规范化课行长表这类结构化清单。

- 所有单元格按字符串取值并 strip，保留前导零（学号/班号不丢位，技术方案 8.1）；
- 表头到字段名的映射由 :data:`ALIASES` 归一（支持中英文/别名列头）；
- 只支持 .xlsx（openpyxl）。xls 需另行确认依赖，见 DEVELOPMENT_PLAN §6。
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅在类型检查期引入，运行时按需延迟导入 openpyxl
    from collections.abc import Iterable


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # Excel 数值单元格 2024.0 → "2024"，避免学号被写成浮点。
        return str(int(value))
    return str(value).strip()


def normalize_header(cell: str) -> str:
    return _clean(cell).replace(" ", "").lower()


def read_tabular_rows(
    data: bytes,
    *,
    sheet_index: int = 0,
    header_row: int = 1,
    required_headers: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """读取 xlsx 指定工作表，返回以**原始表头文本**为键的行字典列表。

    跳过全空行；数值型单元格整数值去尾零。找不到表头行或表头为空抛 ValueError，
    由上层导入服务捕获为 error 级 Issue。
    """
    from openpyxl import load_workbook

    wb = load_workbook(filename=io.BytesIO(bytes(data)), data_only=True)
    try:
        ws = wb.worksheets[sheet_index]
        headers: list[str] = [
            _clean(ws.cell(row=header_row, column=c).value)
            for c in range(1, ws.max_column + 1)
        ]
        if not any(headers):
            raise ValueError("表头行为空")
        normalized = [normalize_header(h) for h in headers]
        if required_headers is not None:
            missing = [
                req
                for req in required_headers
                if normalize_header(req) not in normalized
            ]
            if missing:
                raise ValueError(f"缺少必需列：{', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for r in range(header_row + 1, ws.max_row + 1):
            record: dict[str, str] = {}
            non_empty = False
            for c, h in enumerate(headers, start=1):
                if not h:
                    continue
                v = _clean(ws.cell(row=r, column=c).value)
                record[h] = v
                if v:
                    non_empty = True
            if non_empty:
                rows.append(record)
        return rows
    finally:
        wb.close()


def pick(row: dict[str, str], *names: str) -> str:
    """按候选列名（忽略大小写/空格）取第一个命中的非规范化键值。"""
    normalized = {normalize_header(k): v for k, v in row.items()}
    for n in names:
        v = normalized.get(normalize_header(n))
        if v is not None:
            return v
    return ""
