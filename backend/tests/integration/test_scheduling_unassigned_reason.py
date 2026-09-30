"""自动排班接口对静态资格失败的原因和数量回显。"""

import pytest
from app.modules.inspection.models import InspectionAssignment
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_inspection_assignment import (
    _admin_headers,
    _create_admin_class,
    _make_volunteer,
    _one_task_scene,
)

pytestmark = pytest.mark.integration


def test_auto_reports_qualification_failure_and_exact_counts(
    client: TestClient, session: Session,
) -> None:
    headers = _admin_headers(client, session)
    scene = _one_task_scene(client, headers)
    other_class = _create_admin_class(client, headers, "REASON-OTHER")
    volunteer = _make_volunteer(
        client, headers, session, sem_id=scene["sem_id"],
        username="reason-no-qualification", student_no="REASON-NQ",
        admin_class_id=other_class, qualify=False,
    )
    task_id = int(scene["task"]["id"])

    response = client.post(
        "/api/v1/assignments/auto", headers=headers,
        json={"semester_id": scene["sem_id"], "task_ids": [task_id],
              "candidate_user_ids": [volunteer.id]},
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["target_task_count"] == 1
    assert result["assigned_count"] == 0
    assert result["unassigned_count"] == 1
    assert result["assigned"] == []
    assert [{"task_id": item["task_id"], "reason_code": item["reason_code"]}
            for item in result["unassigned"]] == [
                {"task_id": str(task_id), "reason_code": "NO_QUALIFICATION"},
            ]
    session.expire_all()
    count = session.scalar(select(func.count()).select_from(InspectionAssignment))
    assert count == 0
