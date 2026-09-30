"""真实 MySQL：当前唯一、历史保留及仓储当前受派过滤。"""

from datetime import datetime

import pytest
from app.modules.inspection.models import InspectionAssignment
from app.modules.inspection.repository import InspectionRepository
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.integration import test_inspection_assignment as scene

pytestmark = pytest.mark.integration


def test_revoked_assignments_remain_history_but_do_not_occupy_task(
    client: TestClient, session: Session
) -> None:
    admin = scene._admin_headers(client, session)
    data = scene._one_task_scene(client, admin)
    task_id = int(data["task"]["id"])
    admin_id = scene._role(session, "SUPER_ADMIN").users[0].id
    old = InspectionAssignment(
        task_id=task_id, volunteer_user_id=admin_id,
        assign_method="MANUAL", revoked_at=datetime(2026, 9, 1),
    )
    current = InspectionAssignment(
        task_id=task_id, volunteer_user_id=admin_id,
        assign_method="MANUAL",
    )
    session.add_all([old, current])
    session.commit()
    repo = InspectionRepository(session)
    assert repo.get_assignment_by_task(task_id).id == current.id
    assert repo.get_assignment_by_task_for_update(task_id).id == current.id
    assert repo.list_assignments_by_task_ids([task_id])[task_id].id == current.id
    assert repo.get_assignment(old.id).id == old.id
    assert repo.get_assignment_for_update(old.id).id == old.id
    assert [assignment.id for assignment, _ in repo.list_assignments_for_volunteer_on_date(
        admin_id, datetime(2026, 9, 7).date()
    )] == [current.id]
    assert [row.id for row in session.scalars(
        select(InspectionAssignment)
        .where(InspectionAssignment.task_id == task_id)
        .order_by(InspectionAssignment.id)
    )] == [old.id, current.id]
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(InspectionAssignment(
            task_id=task_id, volunteer_user_id=admin_id, assign_method="AUTO"
        ))
        session.flush()
