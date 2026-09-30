"""MySQL checks for management report discovery and canceled-task recovery boundaries."""

from datetime import date, datetime

import pytest
from app.core.permissions import RoleCode
from app.modules.academic.models import Semester, Student
from app.modules.inspection.models import InspectionSubmission, TaskDeadlineAssessment
from app.modules.report.models import Report, ReportSourceRevision, ReportVersion
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration import test_admin_rbac as rbac
from tests.integration import test_inspection_generate as generation

pytestmark = pytest.mark.integration


def test_report_list_uses_latest_published_version_and_source_revision(
    client: TestClient, session: Session
) -> None:
    rbac._bootstrap(session)
    rbac._make_user(session, "manager", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    rbac._make_user(session, "student", [RoleCode.STUDENT.value])
    semester = Semester(
        code="REPORT_LIST", name="Report list", start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 31), first_monday=date(2026, 9, 7),
        total_weeks=20, status="ACTIVE",
    )
    session.add(semester)
    session.flush()
    report = Report(
        semester_id=semester.id, week_no=1, scope="COLLEGE", latest_version_no=3
    )
    other_scope = Report(
        semester_id=semester.id, week_no=1, scope="CLASS", latest_version_no=0
    )
    session.add_all([report, other_scope])
    session.flush()
    published = ReportVersion(
        report_id=report.id, version_no=1, status="PUBLISHED", source_revision=1,
        generated_at=datetime(2026, 9, 8, 10),
    )
    failed = ReportVersion(
        report_id=report.id, version_no=2, status="FAILED", source_revision=2
    )
    generating = ReportVersion(
        report_id=report.id, version_no=3, status="GENERATING", source_revision=2
    )
    revision = ReportSourceRevision(
        semester_id=semester.id, week_no=1, revision=2
    )
    session.add_all([published, failed, generating, revision])
    session.commit()
    manager = rbac._bearer(rbac._login(client, "manager"))
    response = client.get(
        "/api/v1/reports", headers=manager,
        params={"semester_id": semester.id, "week_no": 1},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert len(data["items"]) == 1
    row = data["items"][0]
    assert row["report_id"] == str(report.id)
    assert row["latest_version_id"] == str(published.id)
    assert row["latest_version_no"] == 1
    assert row["latest_version_created_at"] == "2026-09-08T10:00:00Z"
    assert row["source_changed"] is True
    student = rbac._bearer(rbac._login(client, "student"))
    denied = client.get("/api/v1/reports", headers=student)
    assert denied.status_code == 403, denied.text


def _canceled_future_course(
    client: TestClient, session: Session
) -> tuple[dict[str, str], dict, str, int]:
    headers = generation._admin_headers(client, session)
    scene = generation._scene(client, headers)
    for number, start, end in ((1, "08:00", "08:45"), (2, "08:55", "09:40")):
        response = client.put(
            f"/api/v1/academic/semesters/{scene['semester_id']}"
            f"/period-definitions/{number}",
            headers=headers, json={"start_time": start, "end_time": end},
        )
        assert response.status_code == 200, response.text
    generated = client.post(
        "/api/v1/inspection-tasks/generate", headers=headers,
        json={
            "semester_id": scene["semester_id"], "inspection_type": "COURSE",
            "week_nos": [5], "teaching_class_ids": [scene["tc_id"]],
        },
    )
    assert generated.status_code == 200, generated.text
    task_id = generated.json()["data"]["tasks"][0]["task_id"]
    task = client.get(f"/api/v1/inspection-tasks/{task_id}", headers=headers)
    assert task.status_code == 200, task.text
    canceled = client.post(
        f"/api/v1/inspection-tasks/{task_id}/cancel", headers=headers,
        json={"lock_version": task.json()["data"]["lock_version"]},
    )
    assert canceled.status_code == 200, canceled.text
    return headers, scene, task_id, canceled.json()["data"]["lock_version"]


@pytest.mark.parametrize("boundary", ["started", "submission", "assessment", "version", "roster"])
def test_restore_rejects_changed_or_executed_task(
    boundary: str, client: TestClient, session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, scene, task_id, version = _canceled_future_course(client, session)
    restore_time = datetime(2026, 9, 29, 0)
    if boundary == "started":
        restore_time = datetime(2026, 10, 5, 1)
    elif boundary == "submission":
        actor_id = session.query(generation.UserAccount.id).filter_by(username="admin").scalar()
        assert actor_id is not None
        session.add(InspectionSubmission(
            task_id=int(task_id), attempt_no=1, volunteer_user_id=actor_id,
            roster_version=1, result="NORMAL", review_status="PENDING",
            submitted_at=datetime(2026, 9, 29, 0),
        ))
        session.commit()
    elif boundary == "assessment":
        session.add(TaskDeadlineAssessment(
            task_id=int(task_id), deadline_at_snapshot=datetime(2026, 10, 5, 14),
            result="OVERDUE_UNEXECUTED", evaluated_at=datetime(2026, 10, 5, 14),
        ))
        session.commit()
    elif boundary == "version":
        version -= 1
    elif boundary == "roster":
        student = session.get(Student, int(scene["students"]["S001"]["id"]))
        assert student is not None
        student.name = "Changed roster name"
        session.commit()
    import app.modules.inspection.restore_service as restore_module

    monkeypatch.setattr(restore_module, "utcnow", lambda: restore_time)
    response = client.post(
        f"/api/v1/inspection-tasks/{task_id}/restore",
        headers=headers, json={"lock_version": version},
    )
    assert response.status_code == 409, response.text


def test_exact_occurrence_rejects_forged_date_outside_scope(
    client: TestClient, session: Session
) -> None:
    headers = generation._admin_headers(client, session)
    scene = generation._scene(client, headers)
    listed = client.get(
        "/api/v1/inspection-course-occurrences", headers=headers,
        params={
            "semester_id": scene["semester_id"],
            "date_from": "2026-09-07", "date_to": "2026-09-07",
            "teaching_class_ids": scene["tc_id"],
        },
    )
    assert listed.status_code == 200, listed.text
    selection = listed.json()["data"]
    forged = client.post(
        "/api/v1/inspection-tasks/generate", headers=headers,
        json={
            "semester_id": scene["semester_id"], "inspection_type": "COURSE",
            "selection_revision": selection["selection_revision"],
            "selection_scope": selection["selection_scope"],
            "occurrences": [{
                "course_schedule_id": scene["schedule_id"],
                "inspection_date": "2026-09-14",
            }],
        },
    )
    assert forged.status_code == 422, forged.text
