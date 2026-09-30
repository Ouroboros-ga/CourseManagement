"""V1 周报只允许学院范围，拒绝请求不得留持久化占位。"""

from __future__ import annotations

import pytest
from app.modules.report.models import Report
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration import test_report_version as report_scene

pytestmark = pytest.mark.integration
report_storage = report_scene.report_storage


def test_class_scope_rejected_before_report_row_created(
    client: TestClient, session: Session, report_storage
) -> None:
    _ = report_storage
    headers = report_scene._admin_headers(client, session)
    semester_id = report_scene._setup_sem(client, headers)
    response = client.post(
        "/api/v1/reports/weekly/versions",
        headers=headers,
        json={"semester_id": semester_id, "week_no": 1, "scope": "CLASS"},
    )
    assert response.status_code == 422, response.text
    session.commit()
    session.expire_all()
    assert (
        session.execute(
            select(Report).where(
                Report.semester_id == semester_id,
                Report.week_no == 1,
                Report.scope == "CLASS",
            )
        ).scalar_one_or_none()
        is None
    )
