"""Teacher account and student deactivation contracts on isolated MySQL."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from app.core.permissions import RoleCode
from app.modules.academic.models import Semester, Student, VolunteerQualification
from app.modules.academic.schemas import StudentUpdateRequest
from app.modules.academic.service import AcademicService
from app.modules.identity.models import Permission, UserAccount, UserPermission
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.schemas import AutoAssignRequest
from app.modules.inspection.service import InspectionService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tests.integration import test_admin_rbac as rbac

pytestmark = pytest.mark.integration

_BASE = "/api/v1"
_NEW_PASSWORD = "AnotherPassw0rd#2"


def _admin(client: TestClient, session: Session) -> dict[str, str]:
    rbac._bootstrap(session)
    rbac._make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return rbac._bearer(rbac._login(client, "admin"))


def _create_teacher(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(
        f"{_BASE}/teacher-accounts",
        headers=headers,
        json={
            "username": name,
            "display_name": name,
            "initial_password": rbac._PWD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _refresh_with_old_cookie(client: TestClient, old_token: str):
    client.cookies.clear()
    return client.post(
        f"{_BASE}/auth/refresh", json={"refresh_token": old_token}
    )


def test_super_admin_creates_teacher_and_duplicate_is_conflict(
    client: TestClient, session: Session
) -> None:
    admin = _admin(client, session)
    teacher = _create_teacher(client, admin, "teacher_new")
    assert teacher["username"] == "teacher_new"
    assert "password_hash" not in teacher
    assert "initial_password" not in teacher
    duplicate = client.post(
        f"{_BASE}/teacher-accounts",
        headers=admin,
        json={
            "username": "teacher_new",
            "display_name": "Again",
            "initial_password": rbac._PWD,
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    session.expire_all()
    stored = session.get(UserAccount, int(teacher["id"]))
    assert stored is not None
    assert {role.code for role in stored.roles} == {RoleCode.TEACHER_ADMIN.value}


def test_teacher_cannot_create_teacher(client: TestClient, session: Session) -> None:
    admin = _admin(client, session)
    _create_teacher(client, admin, "teacher_actor")
    teacher = rbac._bearer(rbac._login(client, "teacher_actor"))
    response = client.post(
        f"{_BASE}/teacher-accounts",
        headers=teacher,
        json={
            "username": "forbidden_peer",
            "display_name": "Forbidden",
            "initial_password": rbac._PWD,
        },
    )
    assert response.status_code == 403, response.text


def test_disable_teacher_revokes_access_and_refresh_and_checks_version(
    client: TestClient, session: Session
) -> None:
    admin = _admin(client, session)
    teacher = _create_teacher(client, admin, "teacher_disable")
    credentials = rbac._login(client, "teacher_disable")
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh
    url = f"{_BASE}/teacher-accounts/{teacher['id']}"
    stale = client.patch(
        url, headers=admin, json={"status": "DISABLED", "lock_version": 99}
    )
    assert stale.status_code == 409, stale.text
    assert client.get(f"{_BASE}/me", headers=_bearer(credentials)).status_code == 200
    changed = client.patch(
        url,
        headers=admin,
        json={"status": "DISABLED", "lock_version": teacher["lock_version"]},
    )
    assert changed.status_code == 200, changed.text
    assert client.get(f"{_BASE}/me", headers=_bearer(credentials)).status_code == 401
    assert _refresh_with_old_cookie(client, old_refresh).status_code == 401


def _bearer(credentials: dict[str, str]) -> dict[str, str]:
    return rbac._bearer(credentials)


def test_password_reset_and_self_change_revoke_prior_sessions(
    client: TestClient, session: Session
) -> None:
    admin = _admin(client, session)
    teacher = _create_teacher(client, admin, "teacher_password")
    first = rbac._login(client, "teacher_password")
    first_refresh = client.cookies.get("refresh_token")
    assert first_refresh
    reset = client.post(
        f"{_BASE}/teacher-accounts/{teacher['id']}/password-reset",
        headers=admin,
        json={"new_password": _NEW_PASSWORD, "lock_version": teacher["lock_version"]},
    )
    assert reset.status_code == 204, reset.text
    assert client.get(f"{_BASE}/me", headers=_bearer(first)).status_code == 401
    assert _refresh_with_old_cookie(client, first_refresh).status_code == 401
    second_login = client.post(
        f"{_BASE}/auth/web/login",
        json={"username": "teacher_password", "password": _NEW_PASSWORD},
    )
    assert second_login.status_code == 200, second_login.text
    second = second_login.json()["data"]
    second_refresh = client.cookies.get("refresh_token")
    assert second_refresh
    changed = client.post(
        f"{_BASE}/me/password-change",
        headers=_bearer(second),
        json={"current_password": _NEW_PASSWORD, "new_password": rbac._PWD},
    )
    assert changed.status_code == 204, changed.text
    assert client.get(f"{_BASE}/me", headers=_bearer(second)).status_code == 401
    assert _refresh_with_old_cookie(client, second_refresh).status_code == 401
    assert rbac._login(client, "teacher_password")["access_token"]


def test_last_active_super_admin_cannot_disable_own_mixed_teacher_account(
    client: TestClient, session: Session
) -> None:
    rbac._bootstrap(session)
    mixed = rbac._make_user(
        session,
        "mixed_admin",
        [RoleCode.SUPER_ADMIN.value, RoleCode.TEACHER_ADMIN.value],
    )
    headers = rbac._bearer(rbac._login(client, "mixed_admin"))
    response = client.patch(
        f"{_BASE}/teacher-accounts/{mixed.id}",
        headers=headers,
        json={"status": "DISABLED", "lock_version": mixed.lock_version},
    )
    assert response.status_code == 409, response.text
    session.expire_all()
    assert session.get(UserAccount, mixed.id).status == "ACTIVE"


def test_student_disable_revokes_future_assignment_but_preserves_history(
    client: TestClient, session: Session
) -> None:
    admin = _admin(client, session)
    student = Student(student_no="LIFECYCLE_1", name="Lifecycle", status="ACTIVE")
    semester = Semester(
        code="LIFECYCLE", name="Lifecycle", start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31), first_monday=date(2030, 1, 7),
        total_weeks=20, status="ACTIVE",
    )
    historical_semester = Semester(
        code="LIFECYCLE_OLD", name="Historical", start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31), first_monday=date(2020, 1, 6),
        total_weeks=20, status="ARCHIVED",
    )
    session.add_all([student, semester, historical_semester])
    session.flush()
    bound = rbac._make_user(
        session,
        "lifecycle_user",
        [RoleCode.STUDENT.value, RoleCode.VOLUNTEER.value,
         RoleCode.STUDENT_AFFAIRS_MANAGER.value],
    )
    bound.student_id = student.id
    qualification = VolunteerQualification(
        semester_id=semester.id, student_id=student.id, enabled=True
    )
    optional = session.scalar(select(Permission).where(Permission.code == "statistics.read"))
    assert optional is not None
    admin_id = session.scalar(select(UserAccount.id).where(UserAccount.username == "admin"))
    assert admin_id is not None
    manager_grant = UserPermission(
        user_id=bound.id, permission_id=optional.id, granted_by=admin_id
    )
    future_task = InspectionTask(
        task_key="lifecycle:future", semester_id=semester.id,
        inspection_date=date(2030, 2, 1), week_no=4,
        inspection_type="MORNING_STUDY", start_period=1, end_period=2,
    )
    past_task = InspectionTask(
        task_key="lifecycle:past", semester_id=historical_semester.id,
        inspection_date=date(2020, 2, 1), week_no=4,
        inspection_type="MORNING_STUDY", start_period=1, end_period=2,
    )
    session.add_all([qualification, manager_grant, future_task, past_task])
    session.flush()
    future_assignment = InspectionAssignment(
        task_id=future_task.id, volunteer_user_id=bound.id, assign_method="MANUAL"
    )
    past_assignment = InspectionAssignment(
        task_id=past_task.id, volunteer_user_id=bound.id, assign_method="MANUAL"
    )
    session.add_all([future_assignment, past_assignment])
    session.commit()
    credentials = rbac._login(client, "lifecycle_user")
    response = client.patch(
        f"{_BASE}/academic/students/{student.id}",
        headers=admin, json={"status": "DISABLED"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["unassigned_task_count"] == 1
    session.expire_all()
    assert session.get(UserAccount, bound.id).student_id is None
    assert session.get(VolunteerQualification, qualification.id).enabled is False
    assert session.get(InspectionAssignment, future_assignment.id).revoked_at is not None
    assert session.get(InspectionAssignment, past_assignment.id).revoked_at is None
    roles = {role.code for role in session.get(UserAccount, bound.id).roles}
    assert RoleCode.STUDENT.value not in roles
    assert RoleCode.STUDENT_AFFAIRS_MANAGER.value not in roles
    assert session.scalar(select(UserPermission).where(UserPermission.user_id == bound.id)) is None
    assert client.get(f"{_BASE}/me", headers=_bearer(credentials)).status_code == 401


def test_student_disable_and_manager_dispatch_do_not_deadlock(
    engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manager holds its account row while deactivation attempts to take that row."""
    rbac._bootstrap(session)
    admin = rbac._make_user(session, "concurrent_admin", [RoleCode.SUPER_ADMIN.value])
    manager = rbac._make_user(
        session, "concurrent_manager", [RoleCode.STUDENT_AFFAIRS_MANAGER.value]
    )
    assert manager.student_id is not None
    student_id = manager.student_id
    semester = Semester(
        code="CONCURRENT_LIFECYCLE", name="Concurrent", start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31), first_monday=date(2030, 1, 7),
        total_weeks=20, status="ACTIVE",
    )
    session.add(semester)
    session.commit()
    actor_admin = CurrentUser(
        id=admin.id, username=admin.username, display_name=admin.display_name,
        status="ACTIVE", roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
    )
    actor_manager = CurrentUser(
        id=manager.id, username=manager.username, display_name=manager.display_name,
        status="ACTIVE", roles=[RoleCode.STUDENT_AFFAIRS_MANAGER.value], permissions=[],
    )
    manager_locked = threading.Event()
    academic_guard_finished = threading.Event()
    original_dispatch_guard = InspectionService._require
    original_academic_guard = AcademicService._require_actor_permission

    def hold_manager_lock(self, actor_id: int, code: str) -> None:
        original_dispatch_guard(self, actor_id, code)
        if actor_id == manager.id:
            manager_locked.set()
            academic_guard_finished.wait(timeout=0.4)

    def observe_academic_guard(self, actor_id: int, code: str) -> None:
        original_academic_guard(self, actor_id, code)
        if actor_id == admin.id:
            academic_guard_finished.set()

    monkeypatch.setattr(InspectionService, "_require", hold_manager_lock)
    monkeypatch.setattr(AcademicService, "_require_actor_permission", observe_academic_guard)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def dispatch() -> None:
        with factory() as worker:
            result = InspectionService(worker).auto_assign(
                actor_manager,
                AutoAssignRequest(semester_id=semester.id, inspection_date=date(2030, 2, 1)),
                None,
            )
            assert result.target_task_count == 0

    def disable() -> None:
        with factory() as worker:
            result = AcademicService(worker).update_student(
                actor_admin, student_id,
                StudentUpdateRequest(status="DISABLED"), None,
            )
            assert result.status == "DISABLED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatch_future = pool.submit(dispatch)
        assert manager_locked.wait(timeout=5)
        disable_future = pool.submit(disable)
        dispatch_future.result(timeout=10)
        disable_future.result(timeout=10)
    session.expire_all()
    assert session.get(Student, student_id).status == "DISABLED"
