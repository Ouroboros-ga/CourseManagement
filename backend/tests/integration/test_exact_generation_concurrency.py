"""Concurrent exact generation of one selected course occurrence on MySQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from app.core.permissions import RoleCode
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import InspectionGenerateRequest
from app.modules.inspection.service import InspectionService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tests.integration import test_inspection_generate as generation

pytestmark = pytest.mark.integration


def test_two_admins_generate_same_exact_occurrence_once(
    client: TestClient, session: Session, engine: Engine
) -> None:
    first_headers = generation._admin_headers(client, session)
    second_user = generation._make_user(
        session, "second_admin", [RoleCode.SUPER_ADMIN.value]
    )
    first_user = session.scalar(
        select(generation.UserAccount).where(generation.UserAccount.username == "admin")
    )
    assert first_user is not None
    scene = generation._scene(client, first_headers)
    listed = client.get(
        "/api/v1/inspection-course-occurrences",
        headers=first_headers,
        params={
            "semester_id": scene["semester_id"],
            "date_from": "2026-09-07",
            "date_to": "2026-09-07",
            "teaching_class_ids": scene["tc_id"],
        },
    )
    assert listed.status_code == 200, listed.text
    selection = listed.json()["data"]
    assert len(selection["items"]) == 1
    request = InspectionGenerateRequest.model_validate({
        "semester_id": scene["semester_id"],
        "inspection_type": "COURSE",
        "selection_scope": selection["selection_scope"],
        "selection_revision": selection["selection_revision"],
        "occurrences": [{
            "course_schedule_id": scene["schedule_id"],
            "inspection_date": "2026-09-07",
        }],
    })
    start = Barrier(2)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def generate_as(user_id: int, username: str):
        actor = CurrentUser(
            id=user_id, username=username, display_name=username,
            status="ACTIVE", roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        with factory() as worker:
            start.wait(timeout=5)
            return InspectionService(worker).generate(actor, request, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(generate_as, first_user.id, first_user.username)
        second = pool.submit(generate_as, second_user.id, second_user.username)
        results = [first.result(timeout=20), second.result(timeout=20)]

    assert sorted(result.created for result in results) == [0, 1]
    assert sorted(result.existed for result in results) == [0, 1]
    returned_ids = [result.tasks[0].task_id for result in results]
    assert returned_ids[0] == returned_ids[1]
    session.rollback()
    rows = list(session.scalars(
        select(InspectionTask).where(
            InspectionTask.course_schedule_id == scene["schedule_id"],
            InspectionTask.inspection_date == date(2026, 9, 7),
        )
    ))
    assert len(rows) == 1
    assert str(rows[0].id) == returned_ids[0]
