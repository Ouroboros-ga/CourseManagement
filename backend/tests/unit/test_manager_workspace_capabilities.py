from datetime import date

import pytest
from app.modules.academic.enrollment_models import StudentEnrollment, StudentManagerAppointment
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.organization.service import CampusService
from sqlalchemy import select

from tests.unit.test_enrollment_lifecycle import school as school_fixture


@pytest.fixture(name="school")
def configured_school():
    yield from school_fixture.__wrapped__()


def test_manager_workspace_matches_dated_appointment_and_only_configured_actions(school):
    user = school.get(UserAccount, 3)
    role = school.scalar(select(Role).where(Role.code == "STUDENT_AFFAIRS_MANAGER"))
    school.add(UserRole(user_id=user.id, role_id=role.id))
    school.add(
        StudentEnrollment(
            student_id=1,
            administrative_class_id=1,
            college_id=1,
            effective_from=date(2026, 1, 1),
            status="ENROLLED",
            revision=1,
            historical_confirmed=True,
            snapshot={},
        )
    )
    appointment = StudentManagerAppointment(
        user_id=3,
        college_id=1,
        effective_from=date(2026, 1, 1),
        allowed_actions=["inspection.read", "volunteer.manage"],
    )
    school.add(appointment)
    school.commit()
    actor = CurrentUser(3, user.username, user.display_name, "ACTIVE", [], [])
    service = CampusService(school)
    rows = service.workspaces(actor)
    assert [row["id"] for row in rows] == ["1"]
    actions = rows[0]["capabilities"]
    assert "inspection.read" in actions and "volunteer.group.manage" in actions
    assert "student.manage" not in actions and "academic.manage" not in actions
    assert service._authorize(actor, 1, "volunteer.member.manage").id == 1
    appointment.allowed_actions = ["inspection.read"]
    school.commit()
    assert "volunteer.member.manage" not in service.capabilities(actor, 1)["capabilities"]
