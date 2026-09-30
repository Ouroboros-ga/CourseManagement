"""E2 课表导出接口的权限、班级范围和空结果。"""

from io import BytesIO

import pytest
from app.core.permissions import RoleCode
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from tests.integration import test_academic as scene

pytestmark = pytest.mark.integration
URL = "/api/v1/course-schedules/export"


def _rows(response):
    assert response.status_code == 200, response.text
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    sheet = workbook.active
    assert sheet is not None
    return list(sheet.values)


def test_export_limits_classes_and_preserves_text(client: TestClient, session: Session) -> None:
    admin = scene._admin_headers(client, session)
    semester = scene._create_semester(client, admin, "EXP-1")
    course = scene._create_course(client, admin, "EXP-C")
    first = scene._create_teaching_class(client, admin, semester["id"], course["id"], "EX-1")
    second = scene._create_teaching_class(client, admin, semester["id"], course["id"], "EX-2")
    for tc, room in ((first, "=A101"), (second, "B202")):
        response = client.post(
            "/api/v1/academic/course-schedules", headers=admin,
            json={"teaching_class_id": int(tc["id"]), "weekday": 1,
                  "start_period": 1, "end_period": 2, "classroom": room,
                  "weeks": [1, 3]},
        )
        assert response.status_code == 200, response.text
    rows = _rows(client.get(
        URL, headers=admin,
        params={"semester_id": semester["id"], "teaching_class_ids": first["id"]},
    ))
    assert len(rows) == 2
    assert rows[1] == ("教学班EX-1", "课程EXP-C", None, "1,3", 1, 1, 2, "=A101")


def test_export_empty_and_denied(client: TestClient, session: Session) -> None:
    admin = scene._admin_headers(client, session)
    semester = scene._create_semester(client, admin, "EXP-EMPTY")
    assert len(_rows(client.get(URL, headers=admin, params={"semester_id": semester["id"]}))) == 1
    scene._make_user(session, "student-export", [RoleCode.STUDENT.value])
    student = scene._bearer(scene._login(client, "student-export"))
    denied = client.get(URL, headers=student, params={"semester_id": semester["id"]})
    assert denied.status_code == 403
