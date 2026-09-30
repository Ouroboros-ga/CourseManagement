"""E1 管理提交查询：权限、范围、筛选、历史详情和只读语义。"""

from __future__ import annotations

import pytest
from app.core.permissions import RoleCode
from app.modules.audit.models import AuditLog
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration import test_inspection_review_attendance as scene
from tests.integration import test_inspection_submission as submission_scene

pytestmark = pytest.mark.integration

MANAGEMENT = "/api/v1/management/submissions"


def _pending(client: TestClient, session: Session):
    admin = scene._admin_headers(client, session)
    data = scene._scene(client, admin)
    submission_id = scene._pending_submission(client, admin, session, data)
    return admin, data, submission_id


def _read(client: TestClient, path: str, headers: dict[str, str], **params):
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_management_list_and_detail_allow_teacher_and_super_admin(
    client: TestClient, session: Session
) -> None:
    admin, data, submission_id = _pending(client, session)
    scene._make_user(session, "teacher", [RoleCode.TEACHER_ADMIN.value])
    teacher = scene._bearer(scene._login(client, "teacher"))

    for headers in (teacher, admin):
        listing = _read(client, MANAGEMENT, headers)
        assert listing["total"] == 1
        assert [int(item["id"]) for item in listing["items"]] == [submission_id]
        detail = _read(client, f"{MANAGEMENT}/{submission_id}", headers)
        assert int(detail["id"]) == submission_id
        assert int(detail["task_id"]) == data["task_id"]
        assert detail["review_status"] == "PENDING"
        assert int(detail["task"]["semester_id"]) == data["sem_id"]
        assert detail["task"]["inspection_date"] == "2026-09-07"
        assert detail["task"]["class_name_snapshot"]
        assert detail["task"]["course_name_snapshot"]
        assert detail["task"]["classroom_snapshot"] == "A101"


def test_management_read_denies_volunteer_and_manager_and_keeps_self_route(
    client: TestClient, session: Session
) -> None:
    admin, data, submission_id = _pending(client, session)
    scene._make_user(session, "manager", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    manager = scene._bearer(scene._login(client, "manager"))
    owner_id = session.get(InspectionSubmission, submission_id).volunteer_user_id
    owner = session.get(submission_scene.UserAccount, owner_id)
    assert owner is not None
    volunteer = scene._bearer(scene._login(client, owner.username))

    for headers in (volunteer, manager):
        assert client.get(MANAGEMENT, headers=headers).status_code == 403
        assert client.get(f"{MANAGEMENT}/{submission_id}", headers=headers).status_code == 403

    own = _read(client, f"/api/v1/submissions/{submission_id}", volunteer)
    assert int(own["id"]) == submission_id
    # 超管虽持 submission.read，本人路径仍按提交归属统一返回 404。
    assert client.get(f"/api/v1/submissions/{submission_id}", headers=admin).status_code == 404
    scene._make_user(session, "other_vol", [RoleCode.VOLUNTEER.value])
    other = scene._bearer(scene._login(client, "other_vol"))
    assert client.get(f"/api/v1/submissions/{submission_id}", headers=other).status_code == 404


def test_management_filters_and_stable_pagination(client: TestClient, session: Session) -> None:
    admin, data, first_id = _pending(client, session)
    owner_id = session.get(InspectionSubmission, first_id).volunteer_user_id
    owner = session.get(submission_scene.UserAccount, owner_id)
    assert owner is not None
    volunteer = scene._bearer(scene._login(client, owner.username))
    for previous_id in (first_id,):
        reviewed = client.post(
            f"/api/v1/submissions/{previous_id}/review",
            headers=admin,
            json={"decision": "REJECTED", "comment": "重查"},
        )
        assert reviewed.status_code == 200, reviewed.text
    next_response = client.post(
        f"/api/v1/inspection-tasks/{data['task_id']}/submissions",
        headers=volunteer,
        json=scene._normal_body(),
    )
    assert next_response.status_code == 200, next_response.text
    second_id = int(next_response.json()["data"]["id"])

    all_items = _read(client, MANAGEMENT, admin, page=1, page_size=1)
    page_two = _read(client, MANAGEMENT, admin, page=2, page_size=1)
    assert all_items["total"] == page_two["total"] == 2
    assert [int(all_items["items"][0]["id"]), int(page_two["items"][0]["id"])] == [
        second_id,
        first_id,
    ]

    pending = _read(client, MANAGEMENT, admin, review_status="PENDING")
    rejected = _read(client, MANAGEMENT, admin, review_status="REJECTED")
    assert [int(row["id"]) for row in pending["items"]] == [second_id]
    assert [int(row["id"]) for row in rejected["items"]] == [first_id]
    assert _read(client, MANAGEMENT, admin, semester_id=data["sem_id"])["total"] == 2
    assert _read(client, MANAGEMENT, admin, semester_id=data["sem_id"] + 1)["total"] == 0
    assert _read(client, MANAGEMENT, admin, task_id=data["task_id"])["total"] == 2
    assert _read(client, MANAGEMENT, admin, task_id=data["task_id"] + 1)["total"] == 0
    assert (
        _read(client, MANAGEMENT, admin, date_from="2026-09-07", date_to="2026-09-07")["total"] == 2
    )
    assert _read(client, MANAGEMENT, admin, date_from="2026-09-08")["total"] == 0


def test_management_detail_preserves_roster_and_file_ids_without_storage_secret(
    client: TestClient, session: Session
) -> None:
    admin = scene._admin_headers(client, session)
    data = scene._scene(client, admin)
    scene._shift_deadline(session, data["sem_id"], scene._MON1_D, hours=48)
    volunteer, volunteer_headers = scene._make_volunteer(client, admin, session, data)
    task = scene._task(session, data["task_id"])
    changed = client.post(
        f"/api/v1/inspection-tasks/{data['task_id']}/roster-versions",
        headers=admin,
        json={
            "student_ids": [data["s1"], data["s2"]],
            "reason": "核对名单",
            "lock_version": task.lock_version,
        },
    )
    assert changed.status_code == 200, changed.text
    photo = submission_scene._make_file(session, volunteer.id, tag="management-detail")
    submitted = client.post(
        f"/api/v1/inspection-tasks/{data['task_id']}/submissions",
        headers=volunteer_headers,
        json=scene._abnormal_body(
            [{"student_id": data["s1"], "attendance_type": "LATE", "note": "迟到"}],
            file_ids=[photo.id],
        ),
    )
    assert submitted.status_code == 200, submitted.text
    submission_id = int(submitted.json()["data"]["id"])
    detail = _read(client, f"{MANAGEMENT}/{submission_id}", admin)
    assert int(detail["task_id"]) == data["task_id"]
    assert detail["roster_version"] == 2
    assert int(detail["file_ids"][0]) == photo.id
    assert detail["abnormal_items"][0]["student_no"] == "S001"
    assert detail["abnormal_items"][0]["attendance_type"] == "LATE"
    assert "object_key" not in str(detail)
    assert photo.object_key not in str(detail)
    assert "url" not in str(detail).lower()


def test_management_get_does_not_mutate_submission_task_or_audit(
    client: TestClient, session: Session
) -> None:
    admin, data, submission_id = _pending(client, session)
    session.commit()
    session.expire_all()
    before_submission = session.get(InspectionSubmission, submission_id)
    before_task = session.get(InspectionTask, data["task_id"])
    assert before_submission is not None and before_task is not None
    before = (
        before_submission.review_status,
        before_submission.updated_at,
        before_task.lock_version,
    )
    audit_ids = set(session.execute(select(AuditLog.id)).scalars())
    _read(client, MANAGEMENT, admin)
    _read(client, f"{MANAGEMENT}/{submission_id}", admin)
    session.commit()
    session.expire_all()
    after_submission = session.get(InspectionSubmission, submission_id)
    after_task = session.get(InspectionTask, data["task_id"])
    assert after_submission is not None and after_task is not None
    assert (
        after_submission.review_status,
        after_submission.updated_at,
        after_task.lock_version,
    ) == before
    assert set(session.execute(select(AuditLog.id)).scalars()) == audit_ids


@pytest.mark.parametrize("approve", [False, True])
def test_roster_revise_rejected_after_submission_exists(
    client: TestClient, session: Session, approve: bool
) -> None:
    admin, data, submission_id = _pending(client, session)
    if approve:
        reviewed = client.post(
            f"/api/v1/submissions/{submission_id}/review",
            headers=admin,
            json={"decision": "APPROVED"},
        )
        assert reviewed.status_code == 200, reviewed.text
    session.expire_all()
    task = session.get(InspectionTask, data["task_id"])
    assert task is not None
    revision = client.post(
        f"/api/v1/inspection-tasks/{data['task_id']}/roster-versions",
        headers=admin,
        json={
            "student_ids": [data["s1"], data["s2"]],
            "reason": "名单核对",
            "lock_version": task.lock_version,
        },
    )
    assert revision.status_code == 409, revision.text
    session.expire_all()
    assert session.get(InspectionTask, data["task_id"]).roster_version == 1


def test_review_after_management_read_rejects_stale_action(
    client: TestClient, session: Session
) -> None:
    admin, _data, submission_id = _pending(client, session)
    seen = _read(client, f"{MANAGEMENT}/{submission_id}", admin)
    assert seen["review_status"] == "PENDING"
    first = client.post(
        f"/api/v1/submissions/{submission_id}/review",
        headers=admin,
        json={"decision": "REJECTED"},
    )
    assert first.status_code == 200, first.text
    stale = client.post(
        f"/api/v1/submissions/{submission_id}/review",
        headers=admin,
        json={"decision": "APPROVED"},
    )
    assert stale.status_code == 409, stale.text
