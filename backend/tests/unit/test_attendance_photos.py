"""本人考勤的现场照片：真实 SQLite 关联查询，不使用生产数据。"""

from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.exceptions import FileExpiredError, NotFoundError
from app.modules.academic.models import Student
from app.modules.attendance.models import AttendanceRecord
from app.modules.attendance.service import AttendanceService
from app.modules.file.models import FileObject
from app.modules.file.service import FileService
from app.modules.identity.models import Permission, Role, RolePermission, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionSubmission, SubmissionFile, TaskRosterMember

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_ownership import legacy


@pytest.fixture
def evidence():
    generator = campus_fixture.__wrapped__()
    _, db, admin, _, _, _ = next(generator)
    try:
        cls, _, _, task = legacy(db)
        student = Student(student_no="TEST-1", name="测试学生", administrative_class_id=cls.id)
        another_student = Student(
            student_no="TEST-2", name="另一学生", administrative_class_id=cls.id
        )
        db.add_all([student, another_student])
        db.flush()
        account = UserAccount(display_name="学生账号", student_id=student.id)
        other = UserAccount(display_name="其他账号", student_id=another_student.id)
        db.add_all([account, other])
        db.flush()
        permission = Permission(code="attendance.read", name="考勤读取")
        role = Role(code="STUDENT", name="学生")
        db.add_all([permission, role])
        db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        for user in [account, other]:
            db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add(TaskRosterMember(task_id=task.id, roster_version=1, student_id=student.id,
                               student_no="TEST-1", name="测试学生"))
        record = AttendanceRecord(task_id=task.id, student_id=student.id,
                                  effective_type="NORMAL", current_version=1)
        db.add(record)
        photos = []
        submissions = []
        for attempt, status in enumerate(["APPROVED", "REJECTED", "PENDING"], 1):
            sub = InspectionSubmission(task_id=task.id, attempt_no=attempt,
                                       volunteer_user_id=admin.id, roster_version=1,
                                       result="NORMAL", review_status=status, submitted_at=utcnow())
            photo = FileObject(id=9007199254740992 + attempt, object_key=f"test/{attempt}.jpg",
                               category="SUBMISSION_PHOTO", content_type="image/jpeg",
                               size_bytes=1, sha256="0" * 64, uploader_user_id=admin.id,
                               status="READY", expires_at=utcnow() + timedelta(days=1))
            db.add_all([sub, photo])
            db.flush()
            db.add(SubmissionFile(submission_id=sub.id, file_id=photo.id))
            photos.append(photo)
            submissions.append(sub)
        db.commit()
        actor = CurrentUser(account.id, None, "学生", "ACTIVE", ["STUDENT"], ["attendance.read"])
        stranger = CurrentUser(other.id, None, "其他", "ACTIVE", ["STUDENT"], ["attendance.read"])
        yield db, actor, stranger, record, photos, submissions
    finally:
        generator.close()


def test_attendance_lists_approved_scene_photo_ids_as_strings(evidence):
    db, _, _, record, photos, _ = evidence
    dto = AttendanceService(db)._assemble([record])[0].model_dump(mode="json")
    assert dto["photo_file_ids"] == [str(photos[0].id)]


def test_owner_can_access_but_stranger_pending_and_rejected_are_hidden(evidence):
    db, actor, stranger, _, photos, _ = evidence
    service = FileService(db)
    assert service.can_access(actor, photos[0])
    assert not service.can_access(stranger, photos[0])
    for photo in photos[1:]:
        with pytest.raises(NotFoundError):
            service.get_access(actor, photo.id)


def test_removed_binding_immediately_revokes_photo_access(evidence):
    db, actor, _, _, photos, _ = evidence
    service = FileService(db)
    assert service.can_access(actor, photos[0])
    db.get(UserAccount, actor.id).student_id = None
    db.commit()
    assert not service.can_access(actor, photos[0])


@pytest.mark.parametrize("state", ["PURGED", "PURGE_PENDING", "expired"])
def test_retention_still_applies_to_attendance_owner(evidence, state):
    db, actor, _, _, photos, _ = evidence
    if state == "expired":
        photos[0].expires_at = utcnow() - timedelta(seconds=1)
    else:
        photos[0].status = state
    db.commit()
    with pytest.raises(FileExpiredError):
        FileService(db).get_access(actor, photos[0].id)


def test_category_and_roster_are_required(evidence):
    db, actor, _, record, photos, submissions = evidence
    photos[0].category = "TEMP"
    db.commit()
    assert not FileService(db).can_access(actor, photos[0])
    photos[0].category = "SUBMISSION_PHOTO"
    submissions[0].roster_version = 2
    db.commit()
    assert not FileService(db).can_access(actor, photos[0])
    assert AttendanceService(db)._assemble([record])[0].model_dump()["photo_file_ids"] == []


def test_my_attendance_and_access_http_contract(evidence):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    db, actor, stranger, record, photos, _ = evidence
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        response = client.get("/api/v1/me/attendance")
        assert response.status_code == 200
        rows = response.json()["data"]["items"]
        assert len(rows) == 1
        assert rows[0]["id"] == str(record.id)
        assert rows[0]["photo_file_ids"] == [str(photos[0].id)]
        detail = client.get(f"/api/v1/attendance/{record.id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["photo_file_ids"] == rows[0]["photo_file_ids"]
        access = client.get(f"/api/v1/files/{photos[0].id}/access")
        assert access.status_code == 200
        assert access.json()["data"]["method"] == "GET"
        app.dependency_overrides[get_current_user] = lambda: stranger
        assert client.get("/api/v1/me/attendance").json()["data"]["items"] == []
        assert client.get(f"/api/v1/files/{photos[0].id}/access").status_code == 404


def test_prebinding_and_disabled_accounts_do_not_gain_new_access(evidence):
    from dataclasses import replace

    db, actor, _, _, photos, _ = evidence
    service = FileService(db)
    assert not service.can_access(replace(actor, pre_binding=True), photos[0])
    db.get(UserAccount, actor.id).status = "DISABLED"
    db.commit()
    assert not service.can_access(actor, photos[0])


def test_no_approved_submission_means_no_photos_or_access(evidence):
    db, actor, _, record, photos, submissions = evidence
    submissions[0].review_status = "REJECTED"
    db.commit()
    assert AttendanceService(db)._assemble([record])[0].photo_file_ids == []
    assert not FileService(db).can_access(actor, photos[0])


def test_latest_approved_attempt_is_shared_by_list_and_access(evidence):
    db, actor, _, record, photos, submissions = evidence
    submissions[1].review_status = "APPROVED"
    db.commit()
    assert AttendanceService(db)._assemble([record])[0].photo_file_ids == [str(photos[1].id)]
    assert not FileService(db).can_access(actor, photos[0])
    assert FileService(db).can_access(actor, photos[1])
