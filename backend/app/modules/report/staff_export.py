"""教职工查课记录受限 Excel 导出模块。

依据架构合同与技术方案规范：
- 导出标明学期、教学班/责任班级、任务负责学院、课次、当前认定、来源及导出时间；
- 本人范围约束与页面完全一致，责任视图仅导出有权学生；
- 产出符合 openpyxl 标准的 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
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


def build_staff_export_excel(rows: list[dict[str, Any]]) -> bytes:
    """构建教工只读考勤记录 Excel 字节。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "查课考勤记录"

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

    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = ALIGN_CENTER
        cell.border = BORDER_THIN
    ws.row_dimensions[1].height = 24

    for row_idx, r in enumerate(rows, start=2):
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
        ws.append(data_row)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_num)
            cell.font = DATA_FONT
            cell.border = BORDER_THIN
            if col_num in (1, 2, 4, 5, 7, 8, 9, 12, 13, 14):
                cell.alignment = ALIGN_CENTER
            else:
                cell.alignment = ALIGN_LEFT
        ws.row_dimensions[row_idx].height = 20

    # 自适应列宽
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            # 中文字符算2宽度
            length = sum(2 if ord(char) > 127 else 1 for char in val_str)
            if length > max_len:
                max_len = length
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["XLSX_CONTENT_TYPE", "build_staff_export_excel"]
