"""F 审计查询：权限、有界筛选与历史 JSON 脱敏。"""

from datetime import datetime

import pytest
from app.core.permissions import RoleCode
from app.modules.audit.models import AuditLog
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration import test_academic as scene

pytestmark = pytest.mark.integration
URL = "/api/v1/audit-logs"
WINDOW = {"date_from": "2026-09-01T00:00:00Z", "date_to": "2026-09-30T00:00:00Z"}


def test_audit_read_filters_and_redacts(client: TestClient, session: Session) -> None:
    admin = scene._admin_headers(client, session)
    log = AuditLog(
        actor_user_id=None, action="test.audit", resource_type="course_schedule",
        resource_id="12", created_at=datetime(2026, 9, 20),
        before_json={"status": "ACTIVE", "password_hash": "secret", "proof_text": "private"},
        after_json={"status": "INACTIVE", "token": "secret"},
        reason="free text not included", request_id="req-1",
    )
    session.add(log)
    session.commit()
    response = client.get(URL, headers=admin, params={**WINDOW, "action": "test.audit"})
    assert response.status_code == 200, response.text
    listing = response.json()["data"]
    assert listing["total"] == 1
    assert [item["id"] for item in listing["items"]] == [str(log.id)]
    detail_response = client.get(f"{URL}/{log.id}", headers=admin)
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["before"] == {"status": "ACTIVE"}
    assert detail["after"] == {"status": "INACTIVE"}
    assert "reason" not in detail
    assert "secret" not in detail_response.text


def test_audit_read_denies_non_admin_and_large_window(client: TestClient, session: Session) -> None:
    admin = scene._admin_headers(client, session)
    for role, name in ((RoleCode.TEACHER_ADMIN, "teacher-audit"),
                       (RoleCode.STUDENT_AFFAIRS_MANAGER, "manager-audit")):
        scene._make_user(session, name, [role.value])
        user = scene._bearer(scene._login(client, name))
        assert client.get(URL, headers=user, params=WINDOW).status_code == 403
        assert client.get(f"{URL}/1", headers=user).status_code == 403
    assert client.get(URL, headers=admin, params={
        "date_from": "2026-09-01T00:00:00Z", "date_to": "2026-11-01T00:00:00Z",
    }).status_code == 422
    assert client.get(URL, headers=admin, params={**WINDOW, "page_size": 101}).status_code == 422
