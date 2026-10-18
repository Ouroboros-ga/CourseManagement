import io
import zipfile

import pytest
from app.core.exceptions import AppError
from app.modules.importer.zip_preview import expand_zip, preview_zip

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_importer import prepare, sheet


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def zipped(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files:
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "files",
    [
        [("../outside.csv", b"x")],
        [("nested.zip", b"x")],
        [(f"{i}.csv", b"x") for i in range(21)],
    ],
)
def test_zip_rejects_unsafe_or_excessive_members(files):
    with pytest.raises(AppError):
        expand_zip(zipped(files))


def test_zip_preserves_member_paths_and_xlsx_is_not_recursively_unpacked():
    files = [("班级/课表.xlsx", b"PK\x03\x04sheet"), ("名单.csv", b"data")]
    assert expand_zip(zipped(files)) == files


def test_zip_creates_only_previews_and_keeps_course_type_and_member_errors():
    calls = []

    class Draft:
        def model_dump(self, **kwargs):
            return {"id": "1", "status": "PREVIEW"}

    class Service:
        _session = type("Session", (), {"rollback": lambda self: None})()

        def _require_composite(self, actor_id, target):
            assert (actor_id, target) == (7, "grid_timetable")

        def create_preview(self, actor, **kwargs):
            calls.append(kwargs)
            if kwargs["filename"].endswith("broken.csv"):
                raise AppError("VALIDATION_ERROR", "表格缺少数据", 422)
            return Draft()

    result = preview_zip(
        Service(),
        type("Actor", (), {"id": 7})(),
        zipped([("课程/a.xls", b"a"), ("broken.csv", b"bad")]),
        target="grid_timetable",
        semester_id=2,
        course_type_id=9,
    )
    assert result["business_data_applied"] is False
    assert result["files"][0]["filename"] == "课程/a.xls"
    assert result["errors"] == [{"filename": "broken.csv", "message": "表格缺少数据"}]
    assert all(c["replace"] is False and c["course_type_id"] == 9 for c in calls)


def test_archive_preview_does_not_write_qualification_until_confirmation(campus):
    from app.modules.academic.models import VolunteerQualification
    from app.modules.importer.confirmation_set import ImportConfirmationSet
    from sqlalchemy import select

    service, db, own, _, sid = prepare(campus)
    result = preview_zip(
        service,
        service.actor,
        zipped([("资料/志愿者.xlsx", sheet([["学号", "是否启用"], [own.student_no, "是"]]))]),
        target="volunteer",
        semester_id=sid,
    )
    assert not result["errors"]
    assert db.scalar(select(VolunteerQualification.id)) is None
    confirmation = ImportConfirmationSet(service)
    ids = [int(row["id"]) for row in result["files"]]
    plan = confirmation.preview(ids)
    assert plan["can_confirm"]
    confirmation.confirm(ids, plan["revision"], None)
    assert db.scalar(select(VolunteerQualification.id)) is not None


def test_zip_http_multipart_and_explicit_confirmation(campus):
    from app.core.database import get_db
    from app.modules.academic.models import VolunteerQualification
    from app.modules.attendance.scoped_router import require_business_scoped_enabled
    from app.modules.identity.deps import get_current_user
    from app.modules.importer.confirmation_router import router
    from app.modules.organization.router import require_campus_enabled
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    service, db, own, _, sid = prepare(campus)
    api = FastAPI()
    api.include_router(router, prefix="/api/v1")
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: service.actor
    api.dependency_overrides[require_campus_enabled] = lambda: None
    api.dependency_overrides[require_business_scoped_enabled] = lambda: None
    root = f"/api/v1/colleges/{service.cid}/imports/confirmation-set"
    with TestClient(api) as client:
        response = client.post(
            f"{root}/zip-preview",
            data={"target": "volunteer", "semester_id": str(sid)},
            files={
                "file": (
                    "资料.zip",
                    zipped(
                        [("志愿者.xlsx", sheet([["学号", "是否启用"], [own.student_no, "是"]]))]
                    ),
                    "application/zip",
                )
            },
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert not payload["business_data_applied"] and not payload["errors"]
        assert db.scalar(select(VolunteerQualification.id)) is None
        ids = [row["id"] for row in payload["files"]]
        plan = client.post(f"{root}/preview", json={"batch_ids": ids})
        assert plan.status_code == 200
        confirmed = client.post(
            f"{root}/confirm", json={"batch_ids": ids, "revision": plan.json()["data"]["revision"]}
        )
        assert confirmed.status_code == 200
        assert db.scalar(select(VolunteerQualification.id)) is not None
