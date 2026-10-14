"""院级授权必须随数据库角色、学院和授权生命周期即时变化。"""

from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.identity.models import Role, UserAccount, UserRole
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant


@pytest.fixture(name="campus")
def authorization_lifecycle_fixture():
    yield from campus_fixture.__wrapped__()


def test_teacher_role_revocation_removes_primary_college_actions(campus):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding
    from app.modules.organization.service import CampusService

    service, db, _, teacher, a, _ = campus
    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    db.add(TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])))
    db.commit()

    assert service.list_types(teacher, int(a["id"])) == []
    db.delete(
        db.scalar(
            select(UserRole).where(UserRole.user_id == teacher.id, UserRole.role_id == role.id)
        )
    )
    db.commit()

    with pytest.raises(NotFoundError):
        CampusService(db).list_types(teacher, int(a["id"]))


def test_inactive_primary_college_does_not_derive_default_actions(campus):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    service, db, admin, teacher, a, _ = campus
    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    db.add(TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])))
    db.commit()
    assert service.list_types(teacher, int(a["id"])) == []

    service.update_college(
        admin,
        int(a["id"]),
        {"status": "INACTIVE", "lock_version": a["lock_version"]},
    )

    assert service.workspaces(teacher) == []
    with pytest.raises(NotFoundError):
        service.list_types(teacher, int(a["id"]))


def test_expired_cross_college_grant_cannot_authorize_action(campus):
    from app.modules.organization.service import CampusService

    service, _, admin, teacher, _, b = campus
    grant(
        service,
        admin,
        teacher,
        b,
        ["academic.course_type.read"],
        expires_at=utcnow() - timedelta(seconds=1),
    )

    with pytest.raises(NotFoundError):
        CampusService(service.db).list_types(teacher, int(b["id"]))


def test_existing_attendance_service_rechecks_revoked_grant(campus):
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.attendance.scoped_service import ScopedAttendanceService
    from app.modules.organization.models import ScopedGrant

    from tests.unit.test_scoped_attendance import prepare

    db, teacher, a, _, own, _ = prepare(campus)
    scoped = ScopedAttendanceService(db, teacher, int(a["id"]))
    config, _, admin, _, _, _ = campus
    delegation = db.scalar(
        select(ScopedGrant).where(
            ScopedGrant.user_id == teacher.id,
            ScopedGrant.college_id == int(a["id"]),
        )
    )
    config.revoke_grant(admin, int(a["id"]), delegation.id, delegation.lock_version)

    with pytest.raises(NotFoundError):
        scoped.get_attendance(teacher, own.id)
    assert db.get(AttendanceRecord, own.id) is not None


def test_existing_objection_service_rechecks_disabled_account(campus):
    from app.common.pagination import PageParams
    from app.modules.objection.scoped_service import ScopedObjectionService

    from tests.unit.test_scoped_objection import prepare

    db, teacher, a, _, _, _ = prepare(campus)
    scoped = ScopedObjectionService(db, teacher, int(a["id"]))
    account = db.get(UserAccount, teacher.id)
    account.status = "DISABLED"
    db.commit()

    with pytest.raises(PermissionDeniedError):
        scoped.list_objections(
            teacher,
            PageParams(1, 20),
            attendance_record_id=None,
            final_status=None,
            initial_status=None,
        )


def test_scoped_objection_count_and_detail_hide_foreign_college(campus):
    from app.common.pagination import PageParams
    from app.modules.objection.scoped_service import ScopedObjectionService

    from tests.unit.test_scoped_objection import prepare

    db, teacher, a, _, own, foreign = prepare(campus)
    scoped = ScopedObjectionService(db, teacher, int(a["id"]))
    result = scoped.list_objections(
        teacher,
        PageParams(1, 20),
        attendance_record_id=None,
        final_status=None,
        initial_status=None,
    )

    assert result["total"] == 1
    assert [item["id"] for item in result["items"]] == [str(own.id)]
    with pytest.raises(NotFoundError):
        scoped.get_objection(teacher, foreign.id)
