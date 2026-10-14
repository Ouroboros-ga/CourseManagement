from dataclasses import replace

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import NotFoundError
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.file.models import FileObject
from app.modules.file.service import FileService
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.inspection.models import InspectionSubmission, SubmissionFile

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def setup(campus, monkeypatch):
    config, db, admin, teacher, a, b = campus
    _, _, _, _, own, foreign = prepare(campus)
    role = Role(code="TEACHER_ADMIN", name="Teacher")
    db.add(role)
    db.flush()
    db.add_all(
        [
            UserRole(user_id=teacher.id, role_id=role.id),
            TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])),
        ]
    )
    files = []
    for record in (own, foreign):
        sub = InspectionSubmission(
            task_id=record.task_id,
            attempt_no=1,
            volunteer_user_id=admin.id,
            roster_version=1,
            result="NORMAL",
            review_status="APPROVED",
            submitted_at=utcnow(),
        )
        file = FileObject(
            object_key=f"tests/{record.id}.jpg",
            category="SUBMISSION_PHOTO",
            content_type="image/jpeg",
            size_bytes=1,
            sha256="0" * 64,
            uploader_user_id=admin.id,
            status="READY",
        )
        db.add_all([sub, file])
        db.flush()
        db.add(SubmissionFile(submission_id=sub.id, file_id=file.id))
        files.append(file)
    db.commit()
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    return replace(teacher, permissions=["submission.review"]), files


def test_file_review_permission_cannot_access_foreign_college(campus, monkeypatch):
    teacher, (own, foreign) = setup(campus, monkeypatch)
    db = campus[1]
    service = FileService(db)
    assert service.can_access(teacher, own)
    assert not service.can_access(teacher, foreign)
    with pytest.raises(NotFoundError):
        service.get_access(teacher, foreign.id)


def test_cross_college_read_is_not_review_permission(campus, monkeypatch):
    teacher, (_, foreign) = setup(campus, monkeypatch)
    config, db, admin, _, _, b = campus
    assert not FileService(db).can_access(teacher, foreign)
    grant(config, admin, teacher, b, ["submission.review"])
    assert FileService(db).can_access(teacher, foreign)


def test_stale_or_disabled_uploader_cannot_request_new_url(campus, monkeypatch):
    teacher, (own, _) = setup(campus, monkeypatch)
    db = campus[1]
    own.uploader_user_id = teacher.id
    db.commit()
    service = FileService(db)
    assert service.can_access(teacher, own)
    db.get(UserAccount, teacher.id).status = "DISABLED"
    db.commit()
    assert not service.can_access(teacher, own)
