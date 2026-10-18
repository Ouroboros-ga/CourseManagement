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


def test_secondary_roster_is_ignored_without_duplicate_students():
    data = attendance_book([[None, None, None, "0012345678", "测试甲"]])
    item = inspect_upload(data, "测试2601.xlsx")[0]
    assert item["target"] == "admin_roster" and not item["blocked"]
    payload, issues, summary = parse(data)
    assert len(payload["students"]) == 2
    assert summary["source_sheet"] == "课堂考勤"
    assert summary["ignored_sheets"] == ["辅助名单"]
    assert not [i for i in issues if i["severity"] == "error"]


@pytest.mark.parametrize(
    "secondary",
    [
        [["0099999999", "测试丙"]],
        [["0012345678", "另一姓名"]],
        [["工号", "姓名"], ["00123", "教师甲"]],
    ],
)
def test_secondary_content_does_not_block_or_change_primary_roster(secondary):
    data = attendance_book(secondary)
    assert not inspect_upload(data, "测试2601.xlsx")[0]["blocked"]
    payload, issues, summary = parse(data)
    assert [(s["student_no"], s["name"]) for s in payload["students"]] == [
        ("0012345678", "测试甲"),
        ("0012345679", "测试乙"),
    ]
    assert not issues
    assert summary["ignored_sheets"] == ["辅助名单"]


def test_empty_formatted_auxiliary_is_ignored():
    _, issues, _ = parse(attendance_book([[None, None, None]]))
    assert not issues


@pytest.fixture
def campus():
    from tests.unit.test_campus_configuration import campus as campus_fixture

    yield from campus_fixture.__wrapped__()


def test_real_preview_confirms_only_primary_roster_despite_secondary_differences(campus):
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

    draft = preview(attendance_book([["0099999999", "测试丙"]]))
    assert draft.can_confirm
    confirmation = ImportConfirmationSet(service)
    plan = confirmation.preview([int(draft.id)])
    assert plan["can_confirm"]
    assert set(db.scalars(select(Student.id)).all()) == before_ids
    confirmation.confirm([int(draft.id)], plan["revision"], None)
    created = db.scalars(select(Student).where(Student.id.not_in(before_ids))).all()
    assert {s.student_no for s in created} == {"0012345678", "0012345679"}
