from datetime import date

import pytest
from app.modules.academic.enrollment_models import StudentEnrollment, StudentManagerAppointment
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.policy import MANAGER_FUNCTION_CODES
from app.modules.identity.repository import IdentityRepository
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


INDEPENDENT_CORRECTION_CAPS = {"attendance.correct", "attendance.expected_count_adjust"}


def _manager(school) -> tuple[int, IdentityRepository]:
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
    school.commit()
    return user.id, IdentityRepository(school)


def _appoint(school, user_id: int, college_id: int = 1, **kwargs) -> StudentManagerAppointment:
    appointment = StudentManagerAppointment(
        user_id=user_id,
        college_id=college_id,
        effective_from=date(2026, 1, 1),
        allowed_actions=sorted(MANAGER_FUNCTION_CODES),
        **kwargs,
    )
    school.add(appointment)
    school.commit()
    return appointment


def test_manager_keeps_independent_correction_caps_only_with_valid_appointment(school):
    """DEC-02：负责人默认允许独立更正考勤与调整应到人数，但仍受任命、学院范围和逐人开关约束。"""
    user_id, repo = _manager(school)

    # 无有效任命：两项默认能力不得生效。
    assert not INDEPENDENT_CORRECTION_CAPS & set(repo.list_effective_permissions(user_id))

    appointment = _appoint(school, user_id)
    assert set(repo.list_effective_permissions(user_id)) >= INDEPENDENT_CORRECTION_CAPS

    # 逐人关闭开关：仍可精确收回这两项，其余负责人能力保留。
    appointment.allowed_actions = sorted(MANAGER_FUNCTION_CODES - INDEPENDENT_CORRECTION_CAPS)
    school.commit()
    granted = set(repo.list_effective_permissions(user_id))
    assert not INDEPENDENT_CORRECTION_CAPS & granted
    assert "attendance.read" in granted and "inspection.generate" in granted

    appointment.allowed_actions = sorted(MANAGER_FUNCTION_CODES)
    school.commit()

    # 任命到期：能力随任命失效一并收回，不残留。
    appointment.effective_to = date(2026, 1, 31)
    school.commit()
    assert not INDEPENDENT_CORRECTION_CAPS & set(repo.list_effective_permissions(user_id))
    appointment.effective_to = None
    school.commit()
    assert set(repo.list_effective_permissions(user_id)) >= INDEPENDENT_CORRECTION_CAPS

    # 跨学院任命：本人在读学院与任命学院不一致时不构成有效任命。
    appointment.college_id = 2
    school.commit()
    assert not INDEPENDENT_CORRECTION_CAPS & set(repo.list_effective_permissions(user_id))


def test_submission_review_is_not_granted_by_independent_correction_decision(school):
    """DEC-02 只确认两项更正能力，submission.review 不因此自动获得默认授权。

    当前代码仍把 submission.review 留在负责人默认集合里；本用例把差异钉在测试上，
    待产品对该遗留权限单独决议后，把它移出 DEFAULT_ROLE_PERMISSIONS 并改为反向断言。
    """
    from app.modules.identity.policy import DEFAULT_ROLE_PERMISSIONS

    defaults = DEFAULT_ROLE_PERMISSIONS["STUDENT_AFFAIRS_MANAGER"]
    assert defaults >= INDEPENDENT_CORRECTION_CAPS
    assert "submission.review" in defaults  # 遗留项，等待单独决议
