"""教职工查课记录受限 Excel 导出模块。

依据架构合同与技术方案规范：
- 导出标明学期、教学班/责任班级、任务负责学院、课次、当前认定、来源及导出时间；
- 本人范围约束与页面完全一致，责任视图仅导出有权学生；
- 产出符合 openpyxl 标准的 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
DATA_FONT = Font(name="Microsoft YaHei", size=10)
BORDER_THIN = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")


def build_staff_export_excel(rows: Iterable[dict[str, Any]]) -> bytes:
    """构建教工只读考勤记录 Excel 字节。"""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("查课考勤记录")

    headers = [
        "学期",
        "视角",
        "教学班/责任班级",
        "任务负责学院",
        "查课日期",
        "课程名称",
        "节次/课次",
        "教室",
        "学号",
        "学生姓名",
        "行政班快照",
        "当前认定",
        "考勤版本",
        "导出时间",
    ]

    # 先以有界内存暂存数据并测列宽；超出 1MiB 自动落临时文件，避免保留所有单元格。
    # write-only 的列宽必须在首行写出前确定，因此不能在追加所有行后再遍历工作簿。
    widths = [sum(2 if ord(c) > 127 else 1 for c in h) for h in headers]
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+", encoding="utf-8") as spool:
        for r in rows:
            data_row = [
                r.get("semester_name", ""),
                r.get("view_label", ""),
                r.get("class_name", ""),
                r.get("college_name", ""),
                r.get("inspection_date", ""),
                r.get("course_name", ""),
                r.get("period_desc", ""),
                r.get("classroom", ""),
                r.get("student_no", ""),
                r.get("student_name", ""),
                r.get("class_snapshot", ""),
                r.get("effective_type", ""),
                r.get("current_version", ""),
                r.get("export_time", ""),
            ]
            for i, value in enumerate(data_row):
                width = sum(2 if ord(c) > 127 else 1 for c in str(value or ""))
                widths[i] = max(widths[i], width)
            spool.write(json.dumps(data_row, ensure_ascii=False) + "\n")
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = max(width + 3, 12)
        ws.sheet_format.defaultRowHeight = 20
        ws.row_dimensions[1].height = 24
        cells = []
        for title in headers:
            cell = WriteOnlyCell(ws, value=title)
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            cell.alignment, cell.border = ALIGN_CENTER, BORDER_THIN
            cells.append(cell)
        ws.append(cells)
        spool.seek(0)
        for line in spool:
            cells = []
            for i, value in enumerate(json.loads(line), start=1):
                cell = WriteOnlyCell(ws, value=value)
                cell.font, cell.border = DATA_FONT, BORDER_THIN
                cell.alignment = (
                    ALIGN_CENTER if i in (1, 2, 4, 5, 7, 8, 9, 12, 13, 14) else ALIGN_LEFT
                )
                cells.append(cell)
            ws.append(cells)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["XLSX_CONTENT_TYPE", "build_staff_export_excel"]
