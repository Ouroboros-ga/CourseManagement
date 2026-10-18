from io import BytesIO
from zipfile import ZipFile

import pytest
from app.modules.academic.models import Student
from app.modules.importer.confirmation_set import ImportConfirmationSet
from app.modules.importer.zip_preview import preview_zip
from app.modules.organization.models import College
from sqlalchemy import event, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_staff_importer import setup_env, sheet


@pytest.fixture
def campus():
    yield from campus_fixture.__wrapped__()


def preview(service, content):
    return service.create_preview(
        service.actor,
        target="admin_roster",
        content=content,
        semester_id=None,
        teaching_class_id=None,
        filename="名单.xlsx",
        replace=False,
        request_id=None,
    )


@pytest.mark.parametrize("source", ["人工智能学院", "人工智能学院(低空技术与工程学院)"])
def test_unique_parenthetical_college_name_matches_without_transferring(campus, source):
    service, db, _, cid, _, _ = setup_env(campus)
    db.get(College, cid).name = "人工智能学院（低空技术与工程学院）"
    db.commit()
    result = preview(
        service,
        sheet([["学号", "姓名", "班级", "学院"], ["0099990001", "测试甲", "测试2601", source]]),
    )
    assert not [i for i in result.errors if i["code"] == "COLLEGE_MISMATCH"]


def test_foreign_or_ambiguous_college_name_still_blocks(campus):
    service, db, _, cid, other, _ = setup_env(campus)
    db.get(College, cid).name = "人工智能学院（低空技术与工程学院）"
    db.get(College, other).name = "人工智能学院"
    db.commit()
    result = preview(
        service,
        sheet(
            [["学号", "姓名", "班级", "学院"], ["0099990001", "测试甲", "测试2601", "人工智能学院"]]
        ),
    )
    assert any(i["code"] == "COLLEGE_MISMATCH" for i in result.errors)
    assert not result.can_confirm


def test_zip_reuses_draft_fingerprint_but_confirmation_reads_fresh_state(campus, monkeypatch):
    service, db, actor, _, _, _ = setup_env(campus)
    calls = []
    original = service.source_revision

    def revision():
        calls.append(1)
        return original()

    monkeypatch.setattr(service, "source_revision", revision)
    stream = BytesIO()
    with ZipFile(stream, "w") as z:
        for i in range(3):
            z.writestr(
                f"{i}.xlsx",
                sheet([["学号", "姓名", "班级"], [f"009999000{i}", "测试甲", f"测试{i}班"]]),
            )
    result = preview_zip(service, actor, stream.getvalue(), target="admin_roster")
    assert len(calls) == 1
    assert not result["errors"]
    student = db.scalar(select(Student))
    student.name = "changed fixture"
    student.lock_version += 1
    db.commit()
    plan = ImportConfirmationSet(service).preview([int(d["id"]) for d in result["files"]])
    assert len(calls) == 2
    assert not plan["can_confirm"]
    preview(service, sheet([["学号", "姓名", "班级"], ["0099990010", "测试甲", "测试2601"]]))
    assert len(calls) == 3


def test_student_baseline_and_diff_do_not_query_each_number(campus):
    service, db, _, _, _, _ = setup_env(campus)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "WHERE student.student_no =" in statement:
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", record)
    try:
        result = preview(
            service,
            sheet(
                [["学号", "姓名", "班级"]]
                + [[f"009999{i:04d}", f"测试{i}", "测试2601"] for i in range(40)]
            ),
        )
        ImportConfirmationSet(service).preview([int(result.id)])
    finally:
        event.remove(db.bind, "before_cursor_execute", record)
    assert len(statements) == 0
