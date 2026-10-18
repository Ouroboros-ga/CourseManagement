from io import BytesIO

import pytest
from app.modules.importer.intake import inspect_upload
from app.modules.importer.service import ImporterService
from openpyxl import Workbook


def attendance_book(auxiliary=None):
    book = Workbook()
    book.active.title = "课堂考勤"
    book.active.append(["人工智能学院 测试2601 班级2026年课堂考勤表"])
    book.active.append(["序号", "学号", "姓名"])
    book.active.append([1, "0012345678", "测试甲"])
    book.active.append([2, "0012345679", "测试乙"])
    if auxiliary is not None:
        other = book.create_sheet("辅助名单")
        for row in auxiliary:
            other.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def parse(data):
    return ImporterService.__new__(ImporterService)._parse_admin_roster(data, "测试2601.xlsx")


def test_title_before_headers_is_recognized_as_administrative_roster():
    item = inspect_upload(attendance_book(), "测试2601.xlsx")[0]
    assert item["target"] == "admin_roster"
    assert not item["blocked"]


def test_duplicate_auxiliary_roster_is_checked_without_duplicate_students():
    data = attendance_book([[None, None, None, "0012345678", "测试甲"]])
    item = inspect_upload(data, "测试2601.xlsx")[0]
    assert item["target"] == "admin_roster" and not item["blocked"]
    payload, issues, summary = parse(data)
    assert len(payload["students"]) == 2
    assert summary["source_sheet"] == "课堂考勤"
    assert summary["verified_auxiliary_sheets"] == ["辅助名单"]
    assert not [i for i in issues if i["severity"] == "error"]


def test_auxiliary_additional_student_remains_a_preview_conflict():
    data = attendance_book([["0099999999", "测试丙"]])
    assert not inspect_upload(data, "测试2601.xlsx")[0]["blocked"]
    payload, issues, _ = parse(data)
    assert len(payload["students"]) == 2
    assert any(
        i["code"] == "auxiliary_roster_mismatch"
        and i["sheet"] == "辅助名单"
        and i["row"] == 1
        and i["severity"] == "error"
        for i in issues
    )


def test_auxiliary_same_number_different_name_is_not_merged():
    _, issues, _ = parse(attendance_book([["0012345678", "另一姓名"]]))
    assert any(i["code"] == "auxiliary_roster_mismatch" for i in issues)


def test_unrelated_auxiliary_data_is_not_silently_dropped():
    _, issues, _ = parse(attendance_book([["工号", "姓名"], ["00123", "教师甲"]]))
    assert any(i["code"] == "unsupported_auxiliary_sheet" for i in issues)


def test_empty_formatted_auxiliary_is_ignored():
    _, issues, _ = parse(attendance_book([[None, None, None]]))
    assert not issues


@pytest.fixture
def campus():
    from tests.unit.test_campus_configuration import campus as campus_fixture

    yield from campus_fixture.__wrapped__()


def test_real_preview_blocks_sheet_conflict_and_confirms_consistent_roster(campus):
    from app.modules.academic.models import Student
    from app.modules.importer.confirmation_set import ImportConfirmationSet
    from app.modules.organization.models import College
    from sqlalchemy import select

    from tests.unit.test_staff_importer import setup_env

    service, db, actor, cid, _, _ = setup_env(campus)
    db.get(College, cid).name = "人工智能学院"
    db.commit()
    before_ids = set(db.scalars(select(Student.id)).all())

    def preview(data):
        return service.create_preview(
            actor,
            target="admin_roster",
            content=data,
            semester_id=None,
            teaching_class_id=None,
            filename="测试2601.xlsx",
            replace=False,
            request_id=None,
        )

    bad = preview(attendance_book([["0099999999", "测试丙"]]))
    assert not bad.can_confirm
    confirmation = ImportConfirmationSet(service)
    assert not confirmation.preview([int(bad.id)])["can_confirm"]
    assert set(db.scalars(select(Student.id)).all()) == before_ids
    good = preview(attendance_book([["0012345678", "测试甲"]]))
    assert good.can_confirm
    plan = confirmation.preview([int(good.id)])
    assert plan["can_confirm"]
    confirmation.confirm([int(good.id)], plan["revision"], None)
    assert len(set(db.scalars(select(Student.id)).all()) - before_ids) == 2
