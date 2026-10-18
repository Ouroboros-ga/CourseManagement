from io import BytesIO
from zipfile import ZipFile

import pytest
from app.core.exceptions import AppError
from app.modules.importer.intake import inspect_upload

from tests.unit.test_scoped_importer import sheet


def test_mixed_zip_is_identified_without_creating_previews():
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("教师.xlsx", sheet([["工号", "姓名"], ["00123", "张伟"]]))
        archive.writestr(
            "学生.xlsx", sheet([["学号", "姓名", "行政班"], ["00012", "王同学", "一班"]])
        )
    rows = inspect_upload(stream.getvalue(), "资料.zip")
    assert {row["target"] for row in rows} == {"faculty_staff", "admin_roster"}
    assert all(row["archive_member"] == row["filename"] for row in rows)
    assert all(not row["blocked"] for row in rows)


def test_unknown_headers_remain_visible_for_explicit_type_selection():
    rows = inspect_upload(sheet([["未知列"], ["内容"]]), "资料.xlsx")
    assert rows[0]["target"] is None
    assert not rows[0]["blocked"]
    assert rows[0]["message"]


def test_multiple_populated_sheets_are_not_silently_imported_as_first_sheet():
    import openpyxl

    book = openpyxl.Workbook()
    book.active.append(["工号", "姓名"])
    book.active.append(["00123", "张伟"])
    book.create_sheet("另一份资料").append(["学号", "姓名", "班级"])
    stream = BytesIO()
    book.save(stream)
    row = inspect_upload(stream.getvalue(), "多表.xlsx")[0]
    assert row["blocked"] and "工作表" in row["message"]


def test_inspection_rejects_oversized_input_before_parsing():
    with pytest.raises(AppError):
        inspect_upload(b"a" * (10 * 1024 * 1024 + 1), "大表.xlsx")


def test_group_preview_reads_only_selected_archive_members():
    from app.modules.importer.zip_preview import preview_zip

    calls = []

    class Draft:
        def model_dump(self, **kwargs):
            return {"id": "1", "status": "PREVIEW"}

    class Service:
        def _require_composite(self, actor, target):
            assert target == "faculty_staff"

        def create_preview(self, actor, **kwargs):
            calls.append(kwargs["filename"])
            return Draft()

    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("教师.xlsx", b"teacher")
        archive.writestr("学生.xlsx", b"student")
        archive.writestr("导入说明.txt", "平台模板说明")
    content = stream.getvalue()
    preview_zip(
        Service(),
        type("Actor", (), {"id": 1})(),
        content,
        target="faculty_staff",
        members=["教师.xlsx"],
    )
    assert calls == ["教师.xlsx"]
    with pytest.raises(AppError):
        preview_zip(
            Service(),
            type("Actor", (), {"id": 1})(),
            content,
            target="faculty_staff",
            members=["不存在.xlsx"],
        )


def test_intake_http_reuses_group_confirmation_and_guards_college(campus):
    from app.core.database import get_db
    from app.modules.academic.staff_models import FacultyStaff
    from app.modules.attendance.scoped_router import require_business_scoped_enabled
    from app.modules.identity.deps import get_current_user
    from app.modules.importer.confirmation_router import router as confirmation_router
    from app.modules.importer.intake_router import router
    from app.modules.organization.router import require_campus_enabled
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from tests.unit.test_staff_importer import setup_env

    service, db, actor, cid, other_cid, _ = setup_env(campus)
    api = FastAPI()
    from app.core.exceptions import AppError
    from fastapi.responses import JSONResponse

    @api.exception_handler(AppError)
    async def error_handler(request, exc):
        return JSONResponse({"message": exc.message}, status_code=exc.http_status)

    api.include_router(router, prefix="/api/v1")
    api.include_router(confirmation_router, prefix="/api/v1")
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: actor
    api.dependency_overrides[require_campus_enabled] = lambda: None
    api.dependency_overrides[require_business_scoped_enabled] = lambda: None
    root = f"/api/v1/colleges/{cid}/imports"
    content = sheet([["工号", "姓名"], ["00120", "同批教师"]])
    archive = BytesIO()
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("教师.xlsx", content)
        bundle.writestr("错误课表.xlsx", sheet([["星期"], ["错误"]]))
    with TestClient(api) as client:
        response = client.post(
            root + "/intake/inspect", files={"file": ("混合.zip", archive.getvalue())}
        )
        assert response.status_code == 200
        assert len(response.json()["data"]["files"]) == 2
        assert db.scalar(select(FacultyStaff.id)) is None
        assert client.post(
            f"/api/v1/colleges/{other_cid}/imports/intake/inspect",
            files={"file": ("教师.xlsx", content)},
        ).status_code in (403, 404)
        templates = client.get(root + "/intake/templates")
        assert templates.status_code == 200 and templates.content.startswith(b"PK")
        response = client.post(
            root + "/confirmation-set/zip-preview",
            files={"file": ("混合.zip", archive.getvalue())},
            data={"target": "faculty_staff", "members": '["教师.xlsx"]'},
        )
        assert response.status_code == 200
        batch_ids = [f["id"] for f in response.json()["data"]["files"]]
        plan = client.post(
            root + "/confirmation-set/preview", json={"batch_ids": batch_ids}
        ).json()["data"]
        assert plan["can_confirm"]
        assert (
            client.post(
                root + "/confirmation-set/confirm",
                json={"batch_ids": batch_ids, "revision": plan["revision"]},
            ).status_code
            == 200
        )
        assert db.scalar(select(FacultyStaff.staff_no)) == "00120"
        # The bad later group is not part of the successful staff transaction.
        assert (
            client.post(
                root + "/confirmation-set/zip-preview",
                files={"file": ("混合.zip", archive.getvalue())},
                data={"target": "faculty_staff", "members": "not-json"},
            ).status_code
            == 422
        )
        assert db.scalar(select(FacultyStaff.staff_no)) == "00120"


@pytest.fixture(name="campus")
def configured():
    from tests.unit.test_campus_configuration import campus as campus_fixture

    yield from campus_fixture.__wrapped__()


def test_separate_groups_resolve_new_archives_after_save_and_keep_success(campus):
    from datetime import timedelta

    from app.modules.academic.models import Semester, TeachingClassStudent
    from app.modules.academic.staff_models import ClassStaffResponsibility, TeachingStaffAssignment
    from app.modules.identity.role_scope import business_today
    from app.modules.importer.confirmation_set import ImportConfirmationSet
    from sqlalchemy import select

    from tests.unit.test_staff_importer import setup_env

    service, db, actor, _, _, sid = setup_env(campus)
    semester = db.get(Semester, sid)
    semester.start_date = business_today() - timedelta(days=7)
    semester.end_date = business_today() + timedelta(days=100)
    db.commit()

    def preview(target, rows):
        return service.create_preview(
            actor,
            target=target,
            content=sheet(rows),
            semester_id=sid if target == "timetable" else None,
            teaching_class_id=None,
            filename=f"{target}.xlsx",
            replace=False,
            request_id=None,
        )

    def save(target, rows):
        draft = preview(target, rows)
        wizard = ImportConfirmationSet(service)
        plan = wizard.preview([int(draft.id)])
        assert plan["can_confirm"], plan
        return wizard.confirm([int(draft.id)], plan["revision"], None)

    duties = [["行政班", "班主任工号"], ["资料2601", "00123"]]
    assert not preview("class_responsibility", duties).can_confirm
    save("faculty_staff", [["工号", "姓名"], ["00123", "张老师"]])
    save("admin_roster", [["学号", "姓名", "班级"], ["0001234567", "王同学", "资料2601"]])
    save("class_responsibility", duties)
    save(
        "timetable",
        [
            [
                "教学班码",
                "课程代码",
                "课程名称",
                "星期",
                "开始大节",
                "结束大节",
                "周次",
                "教师工号",
                "任课教师",
            ],
            ["资料2601", "MIXED", "测试课", "1", "1", "1", "1", "00123", "张老师"],
        ],
    )
    assert db.scalar(select(ClassStaffResponsibility.id)) is not None
    assert db.scalar(select(TeachingStaffAssignment.id)) is not None
    assert db.scalar(select(TeachingClassStudent.student_id)) is not None
    # Later invalid responsibility neither revokes saved relationships nor rewrites earlier groups.
    assert not preview(
        "class_responsibility", [["行政班", "班主任工号"], ["资料2601", "不存在"]]
    ).can_confirm
    assert len(db.scalars(select(ClassStaffResponsibility)).all()) == 1
