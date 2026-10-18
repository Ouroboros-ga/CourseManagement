from io import BytesIO
from zipfile import ZipFile

import pytest
from app.modules.importer.catalog import build_template_pack, catalog_items, detect_target
from app.modules.importer.permissions import template_spec
from app.modules.importer.staff_adapter import get_template
from openpyxl import load_workbook


def test_catalog_is_ordered_and_optional_targets_are_not_required():
    items = catalog_items()
    assert [item["target"] for item in items] == [
        "admin_roster", "faculty_staff", "class_responsibility", "timetable",
        "grid_timetable", "volunteer", "roster", "elective_course",
    ]
    assert all(not item["required"] for item in items[-2:])
    assert all(item["manage_permission"] for item in items)


def test_detection_uses_headers_and_preserves_ambiguity():
    assert detect_target(["student_no", "name", "class"]) == "admin_roster"
    assert detect_target(["工号", "教职工姓名"]) == "faculty_staff"
    assert detect_target(["班级", "辅导员工号"]) == "class_responsibility"
    assert detect_target(["学号", "是否启用"]) == "volunteer"
    assert detect_target(["学号"]) is None
    assert detect_target(["行政班"]) is None
    assert detect_target(["行政班", "生效日期"]) is None
    assert detect_target([], "行政班学生名单.xlsx") is None
    assert detect_target(["工号", "姓名", "学号", "班级"]) is None


def test_pack_uses_source_contracts_and_text_identifiers():
    with ZipFile(BytesIO(build_template_pack([
        "faculty_staff", "admin_roster", "grid_timetable",
    ]))) as archive:
        assert any(name.endswith(".txt") for name in archive.namelist())
        sheets = [name for name in archive.namelist() if name.endswith(".xlsx")]
        assert len(sheets) == 2
        for name in sheets:
            target = "faculty_staff" if "教职工" in name else "admin_roster"
            spec = (get_template(target).model_dump() if target == "faculty_staff"
                    else template_spec(target))
            workbook = load_workbook(BytesIO(archive.read(name)))
            sheet = workbook.active
            assert [cell.value for cell in sheet[1]] == [
                column["header"] for column in spec["columns"]
            ]
            for column, cell in zip(spec["columns"], sheet[2], strict=True):
                assert (cell.value or "") == spec["example_rows"][0].get(
                    column["header"], "",
                )
                assert cell.number_format == "@"


def test_unknown_pack_target_is_rejected():
    with pytest.raises(ValueError):
        build_template_pack(["unknown"])
