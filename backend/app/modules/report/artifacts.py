"""版本化周报产物构建（W7c，技术方案 18）。

纯计算、无数据库、无事务：把服务侧算好的聚合 payload 渲染为字节产物——
1. 明细 JSON 快照（含个人异常明细，是"可复核事实"的归档形态）；
2. Excel 工作簿（含汇总、班级、任务及标准格式的"考勤异常详表"）；
3. Word 周报文档（符合高校正式学风考勤通报排版规范，含目标详表格式）。

每次调用 new 一个独立的 Workbook / Document 实例（不复用共享实例），杜绝并发/跨请求串写。
"""

from __future__ import annotations

import datetime as _dt
import io
import json
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 产物的 MIME Content-Type
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JSON_CONTENT_TYPE = "application/json"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 明细快照里个人异常的中文标签，仅用于报表可读性；不改写存储的枚举值。
_TYPE_LABEL = {"LEAVE": "请假", "LATE": "迟到", "ABSENT": "旷课", "NORMAL": "正常"}
# 详表短标签（课堂考勤详表：迟/退/旷/假）
_TYPE_LABEL_SHORT = {"LEAVE": "请假", "LATE": "迟到", "ABSENT": "旷", "EARLY_LEAVE": "早退", "NORMAL": "正常"}
# 详表完整情况标签（自习/日常考勤表：情况）
_TYPE_LABEL_FULL = {"LEAVE": "请假", "LATE": "迟到", "ABSENT": "旷课", "EARLY_LEAVE": "早退", "NORMAL": "正常"}


def _to_serializable(obj: Any) -> Any:
    """兜底把 date/datetime 等转成 ISO 字符串，保证 JSON 可序列化。"""
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    return str(obj)


def build_snapshot_json(payload: dict[str, Any]) -> bytes:
    """渲染明细 JSON 快照（稳定排序、UTF-8、缩进 2，便于归档与复核 diff）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        default=_to_serializable,
    ).encode("utf-8")


# --------------------------------------------------------------------------- #
# Excel 产物构建
# --------------------------------------------------------------------------- #
def build_excel(payload: dict[str, Any]) -> bytes:
    """把聚合结果写成专业格式的 .xlsx（汇总 + 班级 + 任务 + 规范考勤异常详表）。"""
    meta = payload.get("meta", {})
    overall = payload.get("overall", {})
    classes: list[dict[str, Any]] = payload.get("classes", [])
    tasks: list[dict[str, Any]] = payload.get("tasks", [])
    details: list[dict[str, Any]] = payload.get("details", [])

    wb = Workbook()

    # 通用样式定义
    font_header = Font(name="微软雅黑", size=10, bold=True, color="1F2937")
    font_data = Font(name="微软雅黑", size=10, color="111827")
    fill_header = PatternFill(start_color="F2F4F7", end_color="F2F4F7", fill_type="solid")
    fill_header_accent = PatternFill(start_color="EBF3FB", end_color="EBF3FB", fill_type="solid")

    thin_border_side = Side(border_style="thin", color="D1D5DB")
    box_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # Sheet 1：汇总
    ws = wb.active
    ws.title = "汇总"
    ws.append(["学期ID", "周次", "范围", "符合条件任务数", "生成时源修订号"])
    ws.append(
        [
            str(meta.get("semester_id", "")),
            meta.get("week_no", ""),
            meta.get("scope", ""),
            meta.get("eligible_task_count", 0),
            meta.get("source_revision", 0),
        ]
    )
    ws.append([])
    ws.append(["统计可用", "有效应到", "异常合计", "请假", "迟到", "旷课", "出勤缺失率"])
    available = bool(overall.get("statistics_available"))
    rate = overall.get("abnormal_rate")
    ws.append(
        [
            "是" if available else "否（分母≤0，不显示比率）",
            overall.get("expected_count", 0),
            overall.get("abnormal_count", 0),
            overall.get("leave_count", 0),
            overall.get("late_count", 0),
            overall.get("absent_count", 0),
            ("" if rate is None else rate),
        ]
    )

    # Sheet 2：班级
    ws_cls = wb.create_sheet("班级")
    ws_cls.append(
        [
            "班级",
            "有效应到",
            "异常合计",
            "请假",
            "迟到",
            "旷课",
            "缺失率",
            "班级比率可用",
            "剔除任务数",
        ]
    )
    for c in classes:
        ws_cls.append(
            [
                c.get("class_name", ""),
                c.get("expected_count", 0),
                c.get("abnormal_count", 0),
                c.get("leave_count", 0),
                c.get("late_count", 0),
                c.get("absent_count", 0),
                c.get("abnormal_rate") if c.get("abnormal_rate") is not None else "",
                "是" if c.get("class_ratio_available") else "否",
                c.get("excluded_task_count", 0),
            ]
        )

    # Sheet 3：任务
    ws_task = wb.create_sheet("任务")
    ws_task.append(["任务ID", "应到", "异常", "应到已人工调整", "班级比率可用"])
    for t in tasks:
        ws_task.append(
            [
                str(t.get("task_id", "")),
                t.get("expected_count", 0),
                t.get("abnormal_count", 0),
                "是" if t.get("expected_count_adjusted") else "否",
                "是" if t.get("class_ratio_available") else "否",
            ]
        )

    # Sheet 4：详表（严格对齐规范格式：日期 | 班级 | 课程 | 姓名/学号 | 迟/退/旷）
    ws_det = wb.create_sheet("详表")
    headers_det = ["日期", "班级", "课程", "姓名/学号", "迟/退/旷"]
    ws_det.append(headers_det)

    study_records: list[dict[str, Any]] = []

    for d in details:
        date_val = d.get("date_display") or d.get("inspection_date") or ""
        class_val = d.get("class_name_snapshot") or ""
        course_val = d.get("course_name") or d.get("course_name_snapshot") or ""
        name_val = d.get("name") or d.get("student_no") or ""
        raw_type = str(d.get("attendance_type", ""))
        status_val = _TYPE_LABEL_SHORT.get(raw_type, raw_type)
        ins_type = d.get("inspection_type", "COURSE")

        if ins_type in ("MORNING_STUDY", "EVENING_STUDY") or not course_val:
            study_records.append(d)
            if not course_val:
                course_val = "早自习" if ins_type == "MORNING_STUDY" else ("晚自习" if ins_type == "EVENING_STUDY" else "-")

        ws_det.append([date_val, class_val, course_val, name_val, status_val])

    # 美化 Sheet 4 表格样式
    ws_det.freeze_panes = "A2"
    for col_idx in range(1, len(headers_det) + 1):
        cell = ws_det.cell(row=1, column=col_idx)
        cell.font = font_header
        cell.fill = fill_header_accent
        cell.alignment = align_center
        cell.border = box_border

    # 数据行样式设置与根据状态轻量高亮
    font_absent = Font(name="微软雅黑", size=10, bold=True, color="DC2626")  # 旷课红
    font_late = Font(name="微软雅黑", size=10, bold=True, color="D97706")    # 迟到/早退橙
    font_leave = Font(name="微软雅黑", size=10, color="2563EB")              # 请假蓝

    for row_idx in range(2, ws_det.max_row + 1):
        for col_idx in range(1, len(headers_det) + 1):
            cell = ws_det.cell(row=row_idx, column=col_idx)
            cell.font = font_data
            cell.border = box_border
            cell.alignment = align_center
            # 状态列特殊样式
            if col_idx == 5:
                val = str(cell.value or "")
                if val in ("旷课", "旷"):
                    cell.font = font_absent
                elif val in ("迟到", "迟", "早退", "退"):
                    cell.font = font_late
                elif val in ("请假", "假"):
                    cell.font = font_leave

    # Sheet 5：自习与日常考勤（若存在无课程/早晚自习考勤：班级 | 姓名 | 情况 | 日期）
    all_sheets = [ws, ws_cls, ws_task, ws_det]
    if study_records:
        ws_std = wb.create_sheet("自习与日常考勤")
        headers_std = ["班级", "姓名", "情况", "日期"]
        ws_std.append(headers_std)
        ws_std.freeze_panes = "A2"
        for col_idx in range(1, len(headers_std) + 1):
            cell = ws_std.cell(row=1, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header_accent
            cell.alignment = align_center
            cell.border = box_border
        for sd in study_records:
            date_val = sd.get("date_display") or sd.get("inspection_date") or ""
            class_val = sd.get("class_name_snapshot") or ""
            name_val = sd.get("name") or sd.get("student_no") or ""
            raw_type = str(sd.get("attendance_type", ""))
            status_val = _TYPE_LABEL_FULL.get(raw_type, raw_type)
            ws_std.append([class_val, name_val, status_val, date_val])
            cur_r = ws_std.max_row
            for col_idx in range(1, len(headers_std) + 1):
                cell = ws_std.cell(row=cur_r, column=col_idx)
                cell.font = font_data
                cell.border = box_border
                cell.alignment = align_center
                if col_idx == 3:
                    if status_val in ("旷课", "旷"):
                        cell.font = font_absent
                    elif status_val in ("迟到", "迟", "早退", "退"):
                        cell.font = font_late
                    elif status_val in ("请假", "假"):
                        cell.font = font_leave
        all_sheets.append(ws_std)

    # 自适应列宽
    for ws_item in all_sheets:
        for col in ws_item.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                # 中文字符按 2 字符宽度计算
                cell_len = sum(2 if ord(char) > 127 else 1 for char in val_str)
                if cell_len > max_len:
                    max_len = cell_len
            ws_item.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Word (.docx) 产物构建
# --------------------------------------------------------------------------- #
def _format_cell(
    cell: Any,
    bold: bool = False,
    bg_color: str | None = None,
    align: Any = WD_ALIGN_PARAGRAPH.CENTER,
    text_color: str | None = None,
    font_name: str = "微软雅黑",
    font_size_pt: float = 9.5,
) -> None:
    """设置 Word 表格单元格样式（字体、颜色、背景、对齐）。"""
    tcPr = cell._tc.get_or_add_tcPr()
    if bg_color:
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_color}"/>'))
    for p in cell.paragraphs:
        p.alignment = align
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        for r in p.runs:
            r.font.name = font_name
            r._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
            r.font.size = Pt(font_size_pt)
            r.font.bold = bold
            if text_color:
                r.font.color.rgb = RGBColor(
                    int(text_color[:2], 16),
                    int(text_color[2:4], 16),
                    int(text_color[4:], 16),
                )


def _set_table_borders(table: Any, color: str = "D1D5DB") -> None:
    """给 Word 表格设置细灰色网格线。"""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


def build_word_document(payload: dict[str, Any]) -> bytes:
    """根据聚合数据生成符合高校考勤周报规范的 Word 文档（.docx）。"""
    meta = payload.get("meta", {})
    overall = payload.get("overall", {})
    classes: list[dict[str, Any]] = payload.get("classes", [])
    details: list[dict[str, Any]] = payload.get("details", [])

    doc = Document()

    # 页面边距：标准约 2.54cm
    for s in doc.sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.0)
        s.right_margin = Inches(1.0)

    week_no = meta.get("week_no", 1)
    eligible_count = meta.get("eligible_task_count", 0)

    # 1. 主标题
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    title_run = title_p.add_run(f"课堂考勤与学风周报（第 {week_no} 周）")
    title_run.font.name = "微软雅黑"
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)

    # 副标题 / 元信息
    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(16)
    sub_run = sub_p.add_run(
        f"统计范围：全院本科生课堂 | 审核通过课堂：{eligible_count} 堂 | 归档版本：Version {meta.get('version_no', 1)}.0"
    )
    sub_run.font.name = "微软雅黑"
    sub_run.font.size = Pt(9.5)
    sub_run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    # 2. 一、 全院考勤总体概况
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)
    h1_run = h1.add_run("一、 全院考勤总体概况")
    h1_run.font.name = "微软雅黑"
    h1_run.font.size = Pt(12)
    h1_run.font.bold = True
    h1_run.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

    exp_total = overall.get("expected_count", 0)
    norm_total = overall.get("normal_count", 0)
    abn_total = overall.get("abnormal_count", 0)
    leave_total = overall.get("leave_count", 0)
    late_total = overall.get("late_count", 0)
    abs_total = overall.get("absent_count", 0)
    rate_val = overall.get("abnormal_rate")
    rate_str = (
        f"{(1 - rate_val) * 100:.1f}%"
        if rate_val is not None and overall.get("statistics_available")
        else "暂无"
    )

    desc_p = doc.add_paragraph()
    desc_p.paragraph_format.line_spacing = 1.3
    desc_p.paragraph_format.space_after = Pt(8)
    desc_run = desc_p.add_run(
        f"本周全院共计完成查课任务 {eligible_count} 堂，有效应到 {exp_total} 人次，正常出勤 {norm_total} 人次，"
        f"全院综合到课率为 {rate_str}。考勤异常合计 {abn_total} 人次，其中旷课 {abs_total} 人次，"
        f"迟到 {late_total} 人次，请假 {leave_total} 人次。"
    )
    desc_run.font.name = "微软雅黑"
    desc_run.font.size = Pt(10)

    # 概况指标表格
    kpi_tbl = doc.add_table(rows=2, cols=6)
    kpi_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    kpi_headers = ["有效应到", "正常出勤", "旷课人次", "迟到人次", "请假人次", "综合到课率"]
    kpi_values = [str(exp_total), str(norm_total), str(abs_total), str(late_total), str(leave_total), rate_str]
    for i, h in enumerate(kpi_headers):
        c = kpi_tbl.cell(0, i)
        c.text = h
        _format_cell(c, bold=True, bg_color="F3F4F6", align=WD_ALIGN_PARAGRAPH.CENTER)
    for i, v in enumerate(kpi_values):
        c = kpi_tbl.cell(1, i)
        c.text = v
        _format_cell(c, bold=(i == 5), bg_color="FFFFFF", align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_table_borders(kpi_tbl)

    # 3. 二、 各行政班考勤到课率统计
    h2 = doc.add_paragraph()
    h2.paragraph_format.space_before = Pt(16)
    h2.paragraph_format.space_after = Pt(6)
    h2_run = h2.add_run("二、 各行政班考勤到课率统计")
    h2_run.font.name = "微软雅黑"
    h2_run.font.size = Pt(12)
    h2_run.font.bold = True
    h2_run.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

    c_intro = doc.add_paragraph("本周各行政班级考勤数据统计如下：")
    c_intro.paragraph_format.space_after = Pt(8)
    c_intro.runs[0].font.name = "微软雅黑"
    c_intro.runs[0].font.size = Pt(10)

    cls_headers = ["班级", "有效应到", "正常出勤", "旷课", "迟到", "请假", "到课率"]
    cls_tbl = doc.add_table(rows=1 + len(classes), cols=7)
    cls_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, ch in enumerate(cls_headers):
        c = cls_tbl.cell(0, i)
        c.text = ch
        _format_cell(c, bold=True, bg_color="F3F4F6", align=WD_ALIGN_PARAGRAPH.CENTER)
    for row_idx, cls in enumerate(classes, start=1):
        c_exp = cls.get("expected_count", 0)
        c_norm = cls.get("normal_count", 0)
        c_abs = cls.get("absent_count", 0)
        c_late = cls.get("late_count", 0)
        c_leave = cls.get("leave_count", 0)
        c_rate = cls.get("abnormal_rate")
        c_rate_str = (
            f"{(1 - c_rate) * 100:.1f}%"
            if c_rate is not None and cls.get("class_ratio_available")
            else "-"
        )
        vals = [
            cls.get("class_name", ""),
            str(c_exp),
            str(c_norm),
            str(c_abs),
            str(c_late),
            str(c_leave),
            c_rate_str,
        ]
        for col_idx, val in enumerate(vals):
            cell = cls_tbl.cell(row_idx, col_idx)
            cell.text = val
            _format_cell(cell, align=WD_ALIGN_PARAGRAPH.CENTER)
    _set_table_borders(cls_tbl)

    # 4. 详表（严格对齐目标规范格式：日期 | 班级 | 课程 | 姓名/学号 | 迟/退/旷）
    h3 = doc.add_paragraph()
    h3.paragraph_format.space_before = Pt(18)
    h3.paragraph_format.space_after = Pt(8)
    h3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h3_run = h3.add_run("详表")
    h3_run.font.name = "微软雅黑"
    h3_run.font.size = Pt(14)
    h3_run.font.bold = True
    h3_run.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

    det_headers = ["日期", "班级", "课程", "姓名/学号", "迟/退/旷"]
    det_tbl = doc.add_table(rows=1 + (len(details) if details else 1), cols=5)
    det_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, dh in enumerate(det_headers):
        c = det_tbl.cell(0, i)
        c.text = dh
        _format_cell(c, bold=True, bg_color="F3F4F6", align=WD_ALIGN_PARAGRAPH.CENTER)

    study_records: list[dict[str, Any]] = []

    if not details:
        c = det_tbl.cell(1, 0)
        c.text = "（本周无考勤异常记录）"
        for i in range(1, 5):
            det_tbl.cell(1, 0).merge(det_tbl.cell(1, i))
        _format_cell(c, align=WD_ALIGN_PARAGRAPH.CENTER)
    else:
        for row_idx, d in enumerate(details, start=1):
            date_val = d.get("date_display") or d.get("inspection_date") or ""
            class_val = d.get("class_name_snapshot") or ""
            course_val = d.get("course_name") or d.get("course_name_snapshot") or ""
            name_val = d.get("name") or d.get("student_no") or ""
            raw_type = str(d.get("attendance_type", ""))
            status_val = _TYPE_LABEL_SHORT.get(raw_type, raw_type)
            ins_type = d.get("inspection_type", "COURSE")

            if ins_type in ("MORNING_STUDY", "EVENING_STUDY") or not course_val:
                study_records.append(d)
                if not course_val:
                    course_val = "早自习" if ins_type == "MORNING_STUDY" else ("晚自习" if ins_type == "EVENING_STUDY" else "-")

            row_vals = [date_val, class_val, course_val, name_val, status_val]
            for col_idx, val in enumerate(row_vals):
                cell = det_tbl.cell(row_idx, col_idx)
                cell.text = str(val)
                is_abs = status_val in ("旷课", "旷")
                is_late = status_val in ("迟到", "迟", "早退", "退")
                text_color = "DC2626" if is_abs else ("D97706" if is_late else "111827")
                _format_cell(
                    cell,
                    align=WD_ALIGN_PARAGRAPH.CENTER,
                    text_color=text_color,
                    bold=is_abs or is_late,
                )

    det_widths = [Pt(79), Pt(94), Pt(162), Pt(78), Pt(63)]
    for row in det_tbl.rows:
        for idx, w in enumerate(det_widths):
            row.cells[idx].width = w
    _set_table_borders(det_tbl, color="000000")

    # 若存在自习/日常考勤（无课程），追加规范 4 列自习情况表：班级 | 姓名 | 情况 | 日期
    if study_records:
        h4 = doc.add_paragraph()
        h4.paragraph_format.space_before = Pt(18)
        h4.paragraph_format.space_after = Pt(8)
        h4.alignment = WD_ALIGN_PARAGRAPH.CENTER
        h4_run = h4.add_run("自习与日常考勤情况")
        h4_run.font.name = "微软雅黑"
        h4_run.font.size = Pt(13)
        h4_run.font.bold = True
        h4_run.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

        std_headers = ["班级", "姓名", "情况", "日期"]
        std_tbl = doc.add_table(rows=1 + len(study_records), cols=4)
        std_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, sh in enumerate(std_headers):
            c = std_tbl.cell(0, i)
            c.text = sh
            _format_cell(c, bold=True, bg_color="F3F4F6", align=WD_ALIGN_PARAGRAPH.CENTER)

        std_widths = [Pt(100), Pt(75), Pt(75), Pt(75)]
        for row_idx, sd in enumerate(study_records, start=1):
            class_val = sd.get("class_name_snapshot") or ""
            name_val = sd.get("name") or sd.get("student_no") or ""
            raw_type = str(sd.get("attendance_type", ""))
            status_val = _TYPE_LABEL_FULL.get(raw_type, raw_type)
            date_val = sd.get("date_display") or sd.get("inspection_date") or ""
            s_vals = [class_val, name_val, status_val, date_val]
            for col_idx, val in enumerate(s_vals):
                cell = std_tbl.cell(row_idx, col_idx)
                cell.text = str(val)
                is_abs = status_val in ("旷课", "旷")
                is_late = status_val in ("迟到", "迟", "早退", "退")
                text_color = "DC2626" if is_abs else ("D97706" if is_late else "111827")
                _format_cell(
                    cell,
                    align=WD_ALIGN_PARAGRAPH.CENTER,
                    text_color=text_color,
                    bold=is_abs or is_late,
                )
        for row in std_tbl.rows:
            for idx, w in enumerate(std_widths):
                row.cells[idx].width = w
        _set_table_borders(std_tbl, color="000000")

    # 5. 落款
    foot_p = doc.add_paragraph()
    foot_p.paragraph_format.space_before = Pt(24)
    foot_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    foot_run1 = foot_p.add_run("学院学生工作办公室 / 教务办公室\n")
    foot_run1.font.name = "微软雅黑"
    foot_run1.font.size = Pt(10)
    foot_run1.font.bold = True
    now_str = _dt.datetime.now().strftime("%Y年%m月%d日")
    foot_run2 = foot_p.add_run(f"发布日期：{now_str}")
    foot_run2.font.name = "微软雅黑"
    foot_run2.font.size = Pt(9.5)
    foot_run2.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_attendance_analytics_excel(payload: dict[str, Any]) -> bytes:
    """把到课率看板的多维聚合结果输出为专业分析报表 Excel（全院总览看板 + 行政班到课率 + 教学班到课率）。"""
    meta = payload.get("meta", {})
    overall = payload.get("overall", {})
    classes: list[dict[str, Any]] = payload.get("classes", [])
    tasks: list[dict[str, Any]] = payload.get("tasks", [])

    wb = Workbook()

    # 样式定义
    font_title = Font(name="微软雅黑", size=13, bold=True, color="1C1B1A")
    font_section = Font(name="微软雅黑", size=11, bold=True, color="1F2937")
    font_header = Font(name="微软雅黑", size=10, bold=True, color="1F2937")
    font_data = Font(name="微软雅黑", size=10, color="111827")
    font_sub = Font(name="微软雅黑", size=9, color="6B7280")

    font_green = Font(name="微软雅黑", size=10, bold=True, color="15803D")
    font_amber = Font(name="微软雅黑", size=10, bold=True, color="B45309")
    font_red = Font(name="微软雅黑", size=10, bold=True, color="DC2626")
    font_blue = Font(name="微软雅黑", size=10, bold=True, color="2563EB")

    fill_header = PatternFill(start_color="F2F4F7", end_color="F2F4F7", fill_type="solid")
    fill_header_accent = PatternFill(start_color="EAEFF8", end_color="EAEFF8", fill_type="solid")
    fill_green_soft = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")
    fill_amber_soft = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
    fill_red_soft = PatternFill(start_color="FEF2F2", end_color="FEF2F2", fill_type="solid")

    thin_border_side = Side(border_style="thin", color="D1D5DB")
    box_border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # ==================== Sheet 1: 学院考勤总览与看板 ====================
    ws1 = wb.active
    ws1.title = "学院考勤总览与看板"

    ws1.append(["人工智能学院 查课考勤多维数据分析看板"])
    ws1.cell(row=1, column=1).font = font_title
    ws1.merge_cells("A1:H1")
    ws1.row_dimensions[1].height = 28

    week_str = f"第 {meta.get('week_no')} 周" if meta.get("week_no") else f"{meta.get('date_from')} 至 {meta.get('date_to')}"
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws1.append([f"统计范围：学期 #{meta.get('semester_id')} | 周次/区间：{week_str} | 报表生成时间：{now_str}"])
    ws1.cell(row=2, column=1).font = font_sub
    ws1.merge_cells("A2:H2")
    ws1.row_dimensions[2].height = 20
    ws1.append([])

    # 1. 学院宏观指标
    ws1.append(["【一、全院出勤宏观指标概览】"])
    ws1.cell(row=4, column=1).font = font_section
    ws1.merge_cells("A4:H4")

    headers_mac = ["已审核堂数", "有效应到人次", "正常出勤人次", "迟到人次", "旷课人次", "请假人次", "综合到课率", "缺勤异常率"]
    ws1.append(headers_mac)
    for c_idx in range(1, len(headers_mac) + 1):
        cell = ws1.cell(row=5, column=c_idx)
        cell.font = font_header
        cell.fill = fill_header_accent
        cell.alignment = align_center
        cell.border = box_border

    exp_tot = overall.get("expected_count", 0)
    norm_tot = overall.get("normal_count", 0)
    late_tot = overall.get("late_count", 0)
    abs_tot = overall.get("absent_count", 0)
    leave_tot = overall.get("leave_count", 0)
    att_rate_str = f"{(norm_tot / exp_tot * 100):.1f}%" if exp_tot > 0 else "-"
    abn_rate_str = f"{((exp_tot - norm_tot) / exp_tot * 100):.1f}%" if exp_tot > 0 else "-"

    row_mac = [
        meta.get("eligible_task_count", len(tasks)),
        exp_tot,
        norm_tot,
        late_tot,
        abs_tot,
        leave_tot,
        att_rate_str,
        abn_rate_str,
    ]
    ws1.append(row_mac)
    for c_idx in range(1, len(row_mac) + 1):
        cell = ws1.cell(row=6, column=c_idx)
        cell.font = font_data
        cell.alignment = align_center
        cell.border = box_border
        if c_idx == 7:
            cell.font = font_green
        elif c_idx == 8 and abn_rate_str != "-":
            cell.font = font_red

    ws1.append([])

    # 2. 行政班出勤梯队分布
    ws1.append(["【二、行政班到课率梯队表现】"])
    r_tier_start = ws1.max_row
    ws1.cell(row=r_tier_start, column=1).font = font_section
    ws1.merge_cells(f"A{r_tier_start}:D{r_tier_start}")

    headers_tier = ["梯队分类", "到课率区间", "班级数量", "班级占比"]
    ws1.append(headers_tier)
    r_th = ws1.max_row
    for c_idx in range(1, len(headers_tier) + 1):
        cell = ws1.cell(row=r_th, column=c_idx)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = box_border

    total_classes = len(classes)
    t_exc = [c for c in classes if (c.get("attendance_rate") or (c.get("normal_count", 0) / c.get("expected_count", 1) if c.get("expected_count", 0) > 0 else 0)) >= 0.98]
    t_good = [c for c in classes if 0.95 <= (c.get("attendance_rate") or (c.get("normal_count", 0) / c.get("expected_count", 1) if c.get("expected_count", 0) > 0 else 0)) < 0.98]
    t_care = [c for c in classes if 0.90 <= (c.get("attendance_rate") or (c.get("normal_count", 0) / c.get("expected_count", 1) if c.get("expected_count", 0) > 0 else 0)) < 0.95]
    t_warn = [c for c in classes if (c.get("attendance_rate") or (c.get("normal_count", 0) / c.get("expected_count", 1) if c.get("expected_count", 0) > 0 else 0)) < 0.90]

    tier_rows = [
        ("优秀梯队", "≥ 98.0%", len(t_exc), fill_green_soft, font_green),
        ("良好梯队", "95.0% ~ 97.9%", len(t_good), None, font_data),
        ("关注梯队", "90.0% ~ 94.9%", len(t_care), fill_amber_soft, font_amber),
        ("重点预警梯队", "< 90.0%", len(t_warn), fill_red_soft, font_red),
    ]

    for name, rng, count, fill, font in tier_rows:
        pct_str = f"{(count / total_classes * 100):.1f}%" if total_classes > 0 else "0.0%"
        ws1.append([name, rng, count, pct_str])
        cur_r = ws1.max_row
        for c_idx in range(1, 5):
            cell = ws1.cell(row=cur_r, column=c_idx)
            cell.alignment = align_center
            cell.border = box_border
            if fill:
                cell.fill = fill
            cell.font = font

    # 自适应 Sheet 1 列宽
    for col in ws1.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws1.column_dimensions[col_letter].width = max(max_len * 2.2, 14)

    # ==================== Sheet 2: 行政班到课率统计 ====================
    ws2 = wb.create_sheet("行政班到课率统计")
    headers_cls = ["序号", "行政班级", "预警状态", "应到人次", "实到人次", "迟到", "旷课", "请假", "到课率", "缺勤率", "剔除任务", "班级比例可用"]
    ws2.append(headers_cls)
    ws2.freeze_panes = "A2"
    ws2.row_dimensions[1].height = 24

    for c_idx in range(1, len(headers_cls) + 1):
        cell = ws2.cell(row=1, column=c_idx)
        cell.font = font_header
        cell.fill = fill_header_accent
        cell.alignment = align_center
        cell.border = box_border

    # 排序班级：按到课率从低到高（方便重点关注）或从高到低
    sorted_classes = sorted(
        classes,
        key=lambda x: (
            (x.get("attendance_rate") if x.get("attendance_rate") is not None else (x.get("normal_count", 0) / x.get("expected_count", 1) if x.get("expected_count", 0) > 0 else 0)),
            x.get("class_name", "")
        ),
        reverse=True,
    )

    for idx, c in enumerate(sorted_classes, 1):
        c_exp = c.get("expected_count", 0)
        c_norm = c.get("normal_count", 0)
        c_late = c.get("late_count", 0)
        c_abs = c.get("absent_count", 0)
        c_leave = c.get("leave_count", 0)
        c_rate = (c_norm / c_exp) if c_exp > 0 else None
        c_abn = (1.0 - c_rate) if c_rate is not None else None

        if c_rate is None:
            tier_label = "无应到"
            tier_fill = None
            tier_font = font_sub
        elif c_rate >= 0.98:
            tier_label = "优秀"
            tier_fill = fill_green_soft
            tier_font = font_green
        elif c_rate >= 0.95:
            tier_label = "正常"
            tier_fill = None
            tier_font = font_data
        elif c_rate >= 0.90:
            tier_label = "关注"
            tier_fill = fill_amber_soft
            tier_font = font_amber
        else:
            tier_label = "预警"
            tier_fill = fill_red_soft
            tier_font = font_red

        ws2.append([
            idx,
            c.get("class_name", ""),
            tier_label,
            c_exp,
            c_norm,
            c_late,
            c_abs,
            c_leave,
            f"{(c_rate * 100):.1f}%" if c_rate is not None else "-",
            f"{(c_abn * 100):.1f}%" if c_abn is not None else "-",
            c.get("excluded_task_count", 0),
            "是" if c.get("class_ratio_available") else "否",
        ])
        cur_r = ws2.max_row
        for c_idx in range(1, len(headers_cls) + 1):
            cell = ws2.cell(row=cur_r, column=c_idx)
            cell.font = font_data
            cell.alignment = align_center
            cell.border = box_border
            if c_idx == 3:
                cell.font = tier_font
                if tier_fill:
                    cell.fill = tier_fill
            elif c_idx == 9:
                if c_rate is not None and c_rate < 0.90:
                    cell.font = font_red
                    cell.fill = fill_red_soft
                elif c_rate is not None and c_rate >= 0.98:
                    cell.font = font_green

    for col in ws2.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws2.column_dimensions[col_letter].width = max(max_len * 2.0, 11)

    # ==================== Sheet 3: 教学班与课堂到课率明细 ====================
    ws3 = wb.create_sheet("教学班与课堂到课率明细")
    headers_tsk = ["序号", "查课日期", "节次", "课程名称", "教学班/合班", "上课教室", "应到人数", "正常出勤", "迟到", "旷课", "请假", "课堂到课率", "出勤状态"]
    ws3.append(headers_tsk)
    ws3.freeze_panes = "A2"
    ws3.row_dimensions[1].height = 24

    for c_idx in range(1, len(headers_tsk) + 1):
        cell = ws3.cell(row=1, column=c_idx)
        cell.font = font_header
        cell.fill = fill_header_accent
        cell.alignment = align_center
        cell.border = box_border

    sorted_tasks = sorted(
        tasks,
        key=lambda x: (
            str(x.get("inspection_date", "")),
            x.get("start_period", 0) or 0,
            x.get("course_name_snapshot", "") or "",
        ),
    )

    for idx, t in enumerate(sorted_tasks, 1):
        t_exp = t.get("expected_count", 0)
        t_norm = t.get("normal_count", 0)
        t_late = t.get("late_count", 0)
        t_abs = t.get("absent_count", 0)
        t_leave = t.get("leave_count", 0)
        t_rate = (t_norm / t_exp) if t_exp > 0 else None
        
        sp = t.get("start_period")
        ep = t.get("end_period")
        period_str = f"第{sp}-{ep}节" if sp and ep else "-"

        if t_rate is None:
            status_str = "无应到"
            status_font = font_sub
            status_fill = None
        elif t_abs > 0:
            status_str = f"旷课 {t_abs}人"
            status_font = font_red
            status_fill = fill_red_soft
        elif t_late > 0:
            status_str = f"迟到 {t_late}人"
            status_font = font_amber
            status_fill = fill_amber_soft
        elif t_leave > 0:
            status_str = f"请假 {t_leave}人"
            status_font = font_data
            status_fill = None
        else:
            status_str = "全勤"
            status_font = font_green
            status_fill = fill_green_soft

        ws3.append([
            idx,
            str(t.get("inspection_date", "")),
            period_str,
            t.get("course_name_snapshot") or "-",
            t.get("class_name_snapshot") or "-",
            t.get("classroom_snapshot") or "-",
            t_exp,
            t_norm,
            t_late,
            t_abs,
            t_leave,
            f"{(t_rate * 100):.1f}%" if t_rate is not None else "-",
            status_str,
        ])
        cur_r = ws3.max_row
        for c_idx in range(1, len(headers_tsk) + 1):
            cell = ws3.cell(row=cur_r, column=c_idx)
            cell.font = font_data
            cell.alignment = align_center
            cell.border = box_border
            if c_idx == 4 or c_idx == 5:
                cell.alignment = align_left
            elif c_idx == 13:
                cell.font = status_font
                if status_fill:
                    cell.fill = status_fill
            elif c_idx == 12 and t_rate is not None and t_rate < 0.90:
                cell.font = font_red
                cell.fill = fill_red_soft

    # ==================== Sheet 4: 详表 ====================
    details: list[dict[str, Any]] = payload.get("details", [])
    ws4 = wb.create_sheet("详表")
    headers_det = ["日期", "班级", "课程", "姓名/学号", "迟/退/旷"]
    ws4.append(headers_det)
    ws4.freeze_panes = "A2"
    ws4.row_dimensions[1].height = 24

    for c_idx in range(1, len(headers_det) + 1):
        cell = ws4.cell(row=1, column=c_idx)
        cell.font = font_header
        cell.fill = fill_header_accent
        cell.alignment = align_center
        cell.border = box_border

    study_records: list[dict[str, Any]] = []

    for d in details:
        date_val = d.get("date_display") or d.get("inspection_date") or ""
        class_val = d.get("class_name_snapshot") or ""
        course_val = d.get("course_name") or d.get("course_name_snapshot") or ""
        name_val = d.get("name") or d.get("student_no") or ""
        raw_type = str(d.get("attendance_type", ""))
        status_val = _TYPE_LABEL_SHORT.get(raw_type, raw_type)
        ins_type = d.get("inspection_type", "COURSE")

        if ins_type in ("MORNING_STUDY", "EVENING_STUDY") or not course_val:
            study_records.append(d)
            if not course_val:
                course_val = "早自习" if ins_type == "MORNING_STUDY" else ("晚自习" if ins_type == "EVENING_STUDY" else "-")

        ws4.append([date_val, class_val, course_val, name_val, status_val])
        cur_r = ws4.max_row
        for c_idx in range(1, len(headers_det) + 1):
            cell = ws4.cell(row=cur_r, column=c_idx)
            cell.font = font_data
            cell.alignment = align_center
            cell.border = box_border
            if c_idx == 5:
                if status_val in ("旷", "旷课"):
                    cell.font = font_red
                elif status_val in ("迟到", "迟", "早退", "退"):
                    cell.font = font_amber
                elif status_val in ("请假", "假"):
                    cell.font = font_blue

    for col in ws4.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws4.column_dimensions[col_letter].width = max(max_len * 2.0, 12)

    # ==================== Sheet 5: 自习与日常考勤（若存在） ====================
    if study_records:
        ws5 = wb.create_sheet("自习与日常考勤")
        headers_std = ["班级", "姓名", "情况", "日期"]
        ws5.append(headers_std)
        ws5.freeze_panes = "A2"
        ws5.row_dimensions[1].height = 24
        for c_idx in range(1, len(headers_std) + 1):
            cell = ws5.cell(row=1, column=c_idx)
            cell.font = font_header
            cell.fill = fill_header_accent
            cell.alignment = align_center
            cell.border = box_border
        for sd in study_records:
            date_val = sd.get("date_display") or sd.get("inspection_date") or ""
            class_val = sd.get("class_name_snapshot") or ""
            name_val = sd.get("name") or sd.get("student_no") or ""
            raw_type = str(sd.get("attendance_type", ""))
            status_val = _TYPE_LABEL_FULL.get(raw_type, raw_type)
            ws5.append([class_val, name_val, status_val, date_val])
            cur_r = ws5.max_row
            for c_idx in range(1, len(headers_std) + 1):
                cell = ws5.cell(row=cur_r, column=c_idx)
                cell.font = font_data
                cell.alignment = align_center
                cell.border = box_border
                if c_idx == 3:
                    if status_val in ("旷", "旷课"):
                        cell.font = font_red
                    elif status_val in ("迟到", "迟", "早退", "退"):
                        cell.font = font_amber
                    elif status_val in ("请假", "假"):
                        cell.font = font_blue
        for col in ws5.columns:
            col_letter = get_column_letter(col[0].column)
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws5.column_dimensions[col_letter].width = max(max_len * 2.0, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_detail_table_word_document(payload: dict[str, Any]) -> bytes:
    """生成完全对齐目标模板规范（media_1791768520700_0eb30860.docx）的独立考勤异常详表 Word 文档（.docx）。"""
    details: list[dict[str, Any]] = payload.get("details", [])
    doc = Document()

    # 页面边距与原版模板完全一致：上下各 1.0 英寸 (72pt)，左右各 1.25 英寸 (90pt)
    for s in doc.sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.25)
        s.right_margin = Inches(1.25)

    # 居中标题：详表（原版格式：宋体，居中）
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(12)
    run_title = p_title.add_run("详表")
    run_title.font.name = "宋体"
    run_title._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run_title.font.size = Pt(14)
    run_title.font.bold = True

    # 5 列详表：日期 | 班级 | 课程 | 姓名/学号 | 迟/退/旷
    det_headers = ["日期", "班级", "课程", "姓名/学号", "迟/退/旷"]
    det_tbl = doc.add_table(rows=1 + (len(details) if details else 1), cols=5)
    det_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, dh in enumerate(det_headers):
        c = det_tbl.cell(0, i)
        c.text = dh
        _format_cell(c, bold=True, bg_color=None, align=WD_ALIGN_PARAGRAPH.CENTER, font_name="宋体", font_size_pt=10.5)

    study_records: list[dict[str, Any]] = []

    if not details:
        c = det_tbl.cell(1, 0)
        c.text = "（本周无考勤异常记录）"
        for i in range(1, 5):
            det_tbl.cell(1, 0).merge(det_tbl.cell(1, i))
        _format_cell(c, align=WD_ALIGN_PARAGRAPH.CENTER, font_name="宋体", font_size_pt=10.5)
    else:
        for row_idx, d in enumerate(details, start=1):
            date_val = d.get("date_display") or d.get("inspection_date") or ""
            class_val = d.get("class_name_snapshot") or ""
            course_val = d.get("course_name") or d.get("course_name_snapshot") or ""
            name_val = d.get("name") or d.get("student_no") or ""
            raw_type = str(d.get("attendance_type", ""))
            status_val = _TYPE_LABEL_SHORT.get(raw_type, raw_type)
            ins_type = d.get("inspection_type", "COURSE")

            if ins_type in ("MORNING_STUDY", "EVENING_STUDY") or not course_val:
                study_records.append(d)
                if not course_val:
                    course_val = "早自习" if ins_type == "MORNING_STUDY" else ("晚自习" if ins_type == "EVENING_STUDY" else "-")

            row_vals = [date_val, class_val, course_val, name_val, status_val]
            for col_idx, val in enumerate(row_vals):
                cell = det_tbl.cell(row_idx, col_idx)
                cell.text = str(val)
                _format_cell(
                    cell,
                    align=WD_ALIGN_PARAGRAPH.CENTER,
                    font_name="宋体",
                    font_size_pt=10.5,
                )

    # 精确匹配原版模板各列宽度：[79pt, 94pt, 162pt, 78pt, 63pt]
    det_widths = [Pt(79), Pt(94), Pt(162), Pt(78), Pt(63)]
    for row in det_tbl.rows:
        for idx, w in enumerate(det_widths):
            row.cells[idx].width = w
    _set_table_borders(det_tbl, color="000000")

    # 若存在自习类考勤异常，追加 4 列自习表（班级 | 姓名 | 情况 | 日期）
    if study_records:
        h4 = doc.add_paragraph()
        h4.paragraph_format.space_before = Pt(18)
        h4.paragraph_format.space_after = Pt(8)
        h4.alignment = WD_ALIGN_PARAGRAPH.CENTER
        h4_run = h4.add_run("自习与日常考勤情况")
        h4_run.font.name = "宋体"
        h4_run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        h4_run.font.size = Pt(14)
        h4_run.font.bold = True

        std_headers = ["班级", "姓名", "情况", "日期"]
        std_tbl = doc.add_table(rows=1 + len(study_records), cols=4)
        std_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, sh in enumerate(std_headers):
            c = std_tbl.cell(0, i)
            c.text = sh
            _format_cell(c, bold=True, bg_color=None, align=WD_ALIGN_PARAGRAPH.CENTER, font_name="宋体", font_size_pt=10.5)

        std_widths = [Pt(100), Pt(75), Pt(75), Pt(75)]
        for row_idx, sd in enumerate(study_records, start=1):
            class_val = sd.get("class_name_snapshot") or ""
            name_val = sd.get("name") or sd.get("student_no") or ""
            raw_type = str(sd.get("attendance_type", ""))
            status_val = _TYPE_LABEL_FULL.get(raw_type, raw_type)
            date_val = sd.get("date_display") or sd.get("inspection_date") or ""
            s_vals = [class_val, name_val, status_val, date_val]
            for col_idx, val in enumerate(s_vals):
                cell = std_tbl.cell(row_idx, col_idx)
                cell.text = str(val)
                _format_cell(
                    cell,
                    align=WD_ALIGN_PARAGRAPH.CENTER,
                    font_name="宋体",
                    font_size_pt=10.5,
                )
        for row in std_tbl.rows:
            for idx, w in enumerate(std_widths):
                row.cells[idx].width = w
        _set_table_borders(std_tbl, color="000000")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_study_attendance_excel(payload: dict[str, Any]) -> bytes:
    """生成完全对齐目标模板规范（media_1791768559858_5aaaadb8.xlsx）的独立自习与日常考勤 Excel。

    格式：
    Sheet1 表头：班级 | 姓名 | 情况 | 日期
    列宽：A: 14.11, B: 13.0, C: 13.0, D: 13.0
    字体：微软雅黑 10pt
    对齐：居中
    """
    details: list[dict[str, Any]] = payload.get("details", [])

    # 分流自习与日常考勤记录；若无单独标明自习的记录，则将全量异常转换为 4 列日常格式输出
    study_records: list[dict[str, Any]] = []
    other_records: list[dict[str, Any]] = []

    for d in details:
        ins_type = d.get("inspection_type", "COURSE")
        course_val = d.get("course_name") or d.get("course_name_snapshot") or ""
        if ins_type in ("MORNING_STUDY", "EVENING_STUDY") or not course_val:
            study_records.append(d)
        else:
            other_records.append(d)

    target_records = study_records if study_records else other_records

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    headers = ["班级", "姓名", "情况", "日期"]
    ws.append(headers)

    font_cell = Font(name="微软雅黑", size=10, bold=False, color="000000")
    align_center = Alignment(horizontal="center", vertical="center")

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = font_cell
        cell.alignment = align_center

    for item in target_records:
        class_val = item.get("class_name_snapshot") or ""
        name_val = item.get("name") or item.get("student_no") or ""
        raw_type = str(item.get("attendance_type", ""))
        status_val = _TYPE_LABEL_FULL.get(raw_type, raw_type)
        date_val = item.get("date_display") or item.get("inspection_date") or ""
        ws.append([class_val, name_val, status_val, date_val])
        cur_row = ws.max_row
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=cur_row, column=col_idx)
            c.font = font_cell
            c.alignment = align_center

    # 设置与原版 xlsx 一致的标准列宽与行高
    ws.column_dimensions["A"].width = 14.11
    ws.column_dimensions["B"].width = 13.0
    ws.column_dimensions["C"].width = 13.0
    ws.column_dimensions["D"].width = 13.0

    for r in range(1, ws.max_row + 1):
        ws.row_dimensions[r].height = 20

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = [
    "build_snapshot_json",
    "build_excel",
    "build_word_document",
    "build_detail_table_word_document",
    "build_study_attendance_excel",
    "build_attendance_analytics_excel",
    "XLSX_CONTENT_TYPE",
    "JSON_CONTENT_TYPE",
    "DOCX_CONTENT_TYPE",
]
