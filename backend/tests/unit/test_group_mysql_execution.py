"""Run the real two-connection planner only on a verified disposable MySQL schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.modules.academic.models import VolunteerQualification
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.volunteer.member_service import GroupMemberService
from app.modules.volunteer.models import VolunteerGroup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange

pytestmark = pytest.mark.skipif(
    not os.environ.get("CAMPUS_TEST_DATABASE_URL"),
    reason="requires dedicated MySQL *_test database",
)


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_concurrent_group_assignment_uses_real_reader_and_keeps_one_assignment(campus, monkeypatch):
    db, admin, a, sem, group, own, _, _ = arrange(campus, monkeypatch)
    config = campus[0]
    current = db.get(VolunteerGroup, int(group["id"]), populate_existing=True)
    # Explicitly allow the freshman volunteer's own morning class. This changes
    # assignment eligibility only and never writes attendance or a personal timetable.
    config.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": current.lock_version,
            "course_type_ids": group["configuration"]["course_type_ids"],
            "default_effect": "ALLOW",
            "own_class_effect": "ALLOW",
            "daily_limit": 1,
            "weekly_limit": 1,
        },
    )
    volunteer = UserAccount(display_name="fixture volunteer", student_id=own.id, status="ACTIVE")
    role = Role(code="VOLUNTEER", name="fixture volunteer")
    db.add_all([volunteer, role])
    db.flush()
    db.add(UserRole(user_id=volunteer.id, role_id=role.id))
    db.add(
        VolunteerQualification(
            semester_id=sem.id, student_id=own.id, college_id=int(a["id"]), enabled=True
        )
    )
    db.commit()
    GroupMemberService(db, admin, int(a["id"]), int(group["id"])).create(
        {
            "student_id": str(own.id),
            "semester_id": str(sem.id),
            "effective_from": "2026-09-01",
            "effective_to": "2027-01-31",
        }
    )
    service = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "mysql-concurrency",
    }
    generated = service.generate(body, service.preview(body)["selection_revision"])
    task_ids = [str(task_id) for task_id in generated.assignable_task_ids]
    assert len(task_ids) == 1
    db.commit()
    barrier = Barrier(2)
    engine = db.get_bind()

    def assign():
        with Session(engine, expire_on_commit=False) as writer:
            barrier.wait(timeout=10)
            result = GroupSamplingService(writer, admin, int(a["id"]), int(group["id"])).assign(
                {
                    "semester_id": str(sem.id),
                    "task_ids": task_ids,
                }
            )
            return result.assigned_count

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(assign) for _ in range(2)]
        assert sorted(future.result(timeout=35) for future in futures) == [0, 1]
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(InspectionAssignment)
            .where(
                InspectionAssignment.task_id == int(task_ids[0]),
                InspectionAssignment.revoked_at.is_(None),
            )
        )
        == 1
    )
    assert db.get(InspectionTask, int(task_ids[0])).college_id == int(a["id"])
