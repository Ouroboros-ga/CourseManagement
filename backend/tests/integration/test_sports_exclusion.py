"""体育不生成查课目标，历史体育任务也不能再被指派。"""

import pytest
from app.modules.academic.models import Course
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.test_inspection_assignment import (
    _AUTO,
    _TASKS,
    _admin_headers,
    _create_admin_class,
    _create_course,
    _create_tc,
    _enroll,
    _make_volunteer,
    _one_task_scene,
    _schedule,
)
from tests.integration.test_inspection_generate import _GEN, _PREV, _scene

pytestmark = pytest.mark.integration


def test_sports_course_preview_and_generate_create_no_task(
    client: TestClient, session: Session,
) -> None:
    headers = _admin_headers(client, session)
    scene = _scene(client, headers)
    course = session.get(Course, scene["course_id"])
    assert course is not None
    course.course_name = "大学体育1"
    session.commit()
    body = {"semester_id": scene["semester_id"], "inspection_type": "COURSE",
            "week_nos": [1], "teaching_class_ids": [scene["tc_id"]]}

    preview = client.post(_PREV, headers=headers, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["task_count"] == 0
    generated = client.post(_GEN, headers=headers, json=body)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["created"] == 0
    session.expire_all()
    assert session.execute(select(InspectionTask)).scalars().all() == []


def test_legacy_sports_task_rejected_by_manual_and_auto_assignment(
    client: TestClient, session: Session,
) -> None:
    headers = _admin_headers(client, session)
    scene = _one_task_scene(client, headers)
    task_id = int(scene["task"]["id"])
    task = session.get(InspectionTask, task_id)
    assert task is not None
    task.course_name_snapshot = "体育板块"
    session.commit()
    other_class = _create_admin_class(client, headers, "CS2402")
    volunteer = _make_volunteer(
        client, headers, session, sem_id=scene["sem_id"], username="sportsvol",
        student_no="SV1", admin_class_id=other_class,
    )

    manual = client.put(
        f"{_TASKS}/{task_id}/assignment", headers=headers,
        json={"volunteer_user_id": volunteer.id, "lock_version": 0, "reason": "核验历史任务"},
    )
    assert manual.status_code == 422, manual.text
    assert manual.json()["fieldErrors"]["reason_code"] == "COURSE_NOT_INSPECTABLE"
    auto = client.post(
        _AUTO, headers=headers,
        json={"semester_id": scene["sem_id"], "task_ids": [task_id],
              "candidate_user_ids": [volunteer.id]},
    )
    assert auto.status_code == 200, auto.text
    data = auto.json()["data"]
    assert data["assigned_count"] == 0
    assert data["unassigned"][0]["reason_code"] == "COURSE_NOT_INSPECTABLE"
    session.expire_all()
    assert session.execute(select(InspectionAssignment)).scalars().all() == []


def test_volunteer_sports_class_still_blocks_inspection_assignment(
    client: TestClient, session: Session,
) -> None:
    headers = _admin_headers(client, session)
    scene = _one_task_scene(client, headers)
    other_class = _create_admin_class(client, headers, "CS2402")
    volunteer = _make_volunteer(
        client, headers, session, sem_id=scene["sem_id"], username="busyvol",
        student_no="BV1", admin_class_id=other_class,
    )
    sports_course_id = _create_course(client, headers, "PE1")
    sports_course = session.get(Course, sports_course_id)
    assert sports_course is not None
    sports_course.course_name = "大学体育1"
    session.commit()
    sports_tc = _create_tc(client, headers, scene["sem_id"], sports_course_id, "PE-T1")
    assert volunteer.student_id is not None
    _enroll(client, headers, sports_tc, [volunteer.student_id])
    _schedule(client, headers, sports_tc, 1, 2, "田径场")
    task_id = int(scene["task"]["id"])

    manual = client.put(
        f"{_TASKS}/{task_id}/assignment", headers=headers,
        json={"volunteer_user_id": volunteer.id, "lock_version": 0, "reason": "冲突复核"},
    )
    assert manual.status_code == 422, manual.text
    assert manual.json()["fieldErrors"]["reason_code"] == "OWN_CLASS_CONFLICT"
    auto = client.post(
        _AUTO, headers=headers,
        json={"semester_id": scene["sem_id"], "task_ids": [task_id],
              "candidate_user_ids": [volunteer.id]},
    )
    assert auto.status_code == 200, auto.text
    data = auto.json()["data"]
    assert data["assigned_count"] == 0
    assert data["unassigned"][0]["reason_code"] == "OWN_CLASS_CONFLICT"
