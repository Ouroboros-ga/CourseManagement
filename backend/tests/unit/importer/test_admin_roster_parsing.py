"""Unit tests for administrative class roster parsing."""

import io
import openpyxl
import pytest

from app.modules.importer.service import ImporterService


def _create_mock_school_roster() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(1, 1, "人工智能学院 数据科学2601 班级2026年课堂考勤表")
    ws.cell(2, 1, "序号")
    ws.cell(2, 2, "学号")
    ws.cell(2, 3, "姓名")
    ws.cell(4, 1, 1)
    ws.cell(4, 2, "0419260101")
    ws.cell(4, 3, "毕卓凡")
    ws.cell(5, 1, 2)
    ws.cell(5, 2, "0419260102")
    ws.cell(5, 3, "蔡景源")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _create_mock_standard_roster() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(1, 1, "学号")
    ws.cell(1, 2, "姓名")
    ws.cell(1, 3, "班级")
    ws.cell(1, 4, "学院")
    ws.cell(2, 1, "0419260201")
    ws.cell(2, 2, "张三")
    ws.cell(2, 3, "数据科学2602")
    ws.cell(2, 4, "人工智能学院")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_school_attendance_sheet():
    content = _create_mock_school_roster()
    service = ImporterService(None)  # unit test for parse only
    payload, issues, summary = service._parse_admin_roster(content, "数据科学2601.xlsx")

    assert summary["student_count"] == 2
    assert summary["classes_count"] == 1
    assert "数据科学2601" in summary["class_names"]
    assert len(payload["students"]) == 2
    s1 = payload["students"][0]
    assert s1["student_no"] == "0419260101"
    assert s1["name"] == "毕卓凡"
    assert s1["class_name"] == "数据科学2601"
    assert s1["college"] == "人工智能学院"
    assert s1["grade_year"] == 2026


def test_parse_standard_tabular_roster():
    content = _create_mock_standard_roster()
    service = ImporterService(None)
    payload, issues, summary = service._parse_admin_roster(content, "roster.xlsx")

    assert summary["student_count"] == 1
    assert summary["classes_count"] == 1
    assert "数据科学2602" in summary["class_names"]
    s = payload["students"][0]
    assert s["student_no"] == "0419260201"
    assert s["name"] == "张三"
    assert s["class_name"] == "数据科学2602"
    assert s["college"] == "人工智能学院"
