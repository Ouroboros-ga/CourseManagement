import pytest
from app.modules.academic.models import AdministrativeClass
from app.modules.academic.staff_models import ClassStaffResponsibility, FacultyStaff
from app.modules.importer.confirmation_set import ImportConfirmationSet
from app.modules.importer.intake import inspect_upload
from app.modules.organization.models import College
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as fixture
from tests.unit.test_staff_importer import setup_env, sheet


@pytest.fixture
def campus():
    yield from fixture.__wrapped__()


def prepare(campus):
    service, db, actor, cid, other, _ = setup_env(campus)
    college = db.get(College, cid)
    college.name = "人工智能学院（低空技术与工程学院）"
    db.add(AdministrativeClass(college_id=cid, class_code="CS2601", class_name="计算机2601"))
    for no, name in [("001", "测试甲"), ("002", "测试乙"), ("003", "测试丙")]:
        db.add(
            FacultyStaff(
                school_id=college.school_id, college_id=cid, staff_no=no, name=name, status="ACTIVE"
            )
        )
    db.commit()
    return service, db, actor, cid, other


def preview(service, rows):
    return service.create_preview(
        service.actor,
        target="class_responsibility",
        semester_id=None,
        teaching_class_id=None,
        replace=False,
        filename="责任区名单.xlsx",
        request_id=None,
        content=sheet(
            [
                ["二级学院学生责任区辅导员、班主任名单"],
                [],
                ["序号", "学院", "班级", "班主任", "辅导员"],
            ]
            + rows
        ),
    )


def test_photo_headers_identify_responsibility_target():
    item = inspect_upload(
        sheet(
            [
                ["二级学院学生责任区辅导员、班主任名单"],
                [],
                ["序号", "学院", "班级", "班主任", "辅导员"],
                [13, "人工智能学院", "计算机2601", "测试甲", "测试乙"],
            ]
        ),
        "名单.xlsx",
    )[0]
    assert item["target"] == "class_responsibility"
    assert not item["blocked"]


def test_original_format_uses_unique_existing_class_alias_and_real_staff(campus):
    service, db, actor, _, _ = prepare(campus)
    draft = preview(service, [[13, "人工智能学院", "计算机类2601", "测试甲", "测试乙"]])
    assert draft.can_confirm, draft.errors
    assert draft.summary["duty_count"] == 2
    plan = ImportConfirmationSet(service).preview([int(draft.id)])
    assert plan["can_confirm"], plan
    assert {c["source"]["row"] for c in plan["files"][0]["changes"]} == {4}
    ImportConfirmationSet(service).confirm([int(draft.id)], plan["revision"], None)
    assert len(db.scalars(select(ClassStaffResponsibility)).all()) == 2


def test_photo_duplicate_class_with_different_head_teachers_blocks(campus):
    service, _, _, _, _ = prepare(campus)
    draft = preview(
        service,
        [
            [13, "人工智能学院", "计算机2601", "测试甲", "测试丙"],
            [15, "人工智能学院", "计算机2601", "测试乙", "测试丙"],
        ],
    )
    assert not draft.can_confirm
    assert any(e["code"] == "DUPLICATE_RESPONSIBILITY" for e in draft.errors)


def test_foreign_college_text_is_not_ignored(campus):
    service, _, _, _, _ = prepare(campus)
    draft = preview(service, [[13, "其他学院", "计算机2601", "测试甲", "测试乙"]])
    assert not draft.can_confirm
    assert any(e["code"] == "COLLEGE_MISMATCH" for e in draft.errors)
