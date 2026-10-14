"""Runtime acceptance: isolated synthetic HTTP, or read-only production evidence.

Run from deployed backend with its environment loaded. Never prints identities,
credentials, signed URLs, photo content or student data.
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.getcwd())


def synthetic():
    import logging
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app import models  # noqa: F401
    from app.core.database import Base, get_db, utcnow
    from app.main import create_app
    from app.modules.academic.models import Course, Semester, Student, TeachingClass
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.file.models import FileObject
    from app.modules.file.router import get_service
    from app.modules.file.service import FileService
    from app.modules.file.storage import LocalStorage
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.models import Permission, Role, RolePermission, UserAccount, UserRole
    from app.modules.identity.service import CurrentUser
    from app.modules.inspection.models import InspectionSubmission, InspectionTask, SubmissionFile, TaskRosterMember

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db, TemporaryDirectory() as directory:
        students = [Student(student_no=f"TEST-{i}", name="Synthetic") for i in range(2)]
        db.add_all(students)
        db.flush()
        users = [UserAccount(display_name="Synthetic", student_id=s.id) for s in students]
        volunteer = UserAccount(display_name="Synthetic volunteer")
        semester = Semester(code="TEST", name="Synthetic", start_date=date(2026, 9, 1),
                            end_date=date(2027, 1, 30), first_monday=date(2026, 8, 31))
        course = Course(course_code="TEST", course_name="Synthetic")
        role = Role(code="STUDENT", name="Synthetic")
        permission = Permission(code="attendance.read", name="Synthetic")
        db.add_all(users + [volunteer, semester, course, role, permission])
        db.flush()
        teaching = TeachingClass(semester_id=semester.id, course_id=course.id, class_name="Synthetic")
        db.add(teaching)
        db.flush()
        task = InspectionTask(task_key="TEST", semester_id=semester.id,
                              inspection_date=date(2026, 9, 7), week_no=2, inspection_type="COURSE",
                              teaching_class_id=teaching.id, start_period=1, end_period=2)
        db.add(task)
        db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        for user in users:
            db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add(TaskRosterMember(task_id=task.id, roster_version=1, student_id=students[0].id,
                                student_no="TEST-0", name="Synthetic"))
        record = AttendanceRecord(task_id=task.id, student_id=students[0].id,
                                  effective_type="NORMAL", current_version=1)
        sub = InspectionSubmission(task_id=task.id, attempt_no=1, volunteer_user_id=volunteer.id,
                                   roster_version=1, result="NORMAL", review_status="APPROVED",
                                   submitted_at=utcnow())
        photo = FileObject(id=9007199254740993, object_key="test/photo.jpg", category="SUBMISSION_PHOTO",
                           content_type="image/jpeg", size_bytes=5, sha256="0" * 64,
                           uploader_user_id=volunteer.id, status="READY",
                           expires_at=utcnow() + timedelta(days=1))
        db.add_all([record, sub, photo])
        db.flush()
        db.add(SubmissionFile(submission_id=sub.id, file_id=photo.id))
        db.commit()
        storage = LocalStorage(directory, "synthetic-only-secret")
        storage.save(photo.object_key, b"photo", "image/jpeg")
        service = FileService(db, storage)
        actor = CurrentUser(users[0].id, None, "Synthetic", "ACTIVE", ["STUDENT"], ["attendance.read"])
        other = CurrentUser(users[1].id, None, "Synthetic", "ACTIVE", ["STUDENT"], ["attendance.read"])
        app = create_app()
        logging.getLogger("httpx").setLevel(logging.WARNING)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: actor
        app.dependency_overrides[get_service] = lambda: service
        with TestClient(app) as client:
            rows = client.get("/api/v1/me/attendance").json()["data"]["items"]
            assert rows[0]["photo_file_ids"] == [str(photo.id)]
            access = client.get(f"/api/v1/files/{photo.id}/access")
            assert access.status_code == 200
            download = client.get(access.json()["data"]["url"])
            assert download.status_code == 200 and download.content == b"photo"
            app.dependency_overrides[get_current_user] = lambda: other
            assert client.get(f"/api/v1/files/{photo.id}/access").status_code == 404
            users[0].student_id = None
            db.commit()
            app.dependency_overrides[get_current_user] = lambda: actor
            assert client.get(f"/api/v1/files/{photo.id}/access").status_code == 404
    engine.dispose()
    print(json.dumps({"synthetic_http": True, "signed_download": True, "cross_student_denied": True,
                      "unbound_denied": True, "bigint_string": True}))


def live():
    import re
    import urllib.error
    import urllib.request

    from sqlalchemy import select

    from app.core.database import get_session_factory, utcnow
    from app.modules.attendance.evidence import attendance_photo_query
    from app.modules.attendance.models import AttendanceRecord
    from app.modules.attendance.service import AttendanceService
    from app.modules.file.models import FileObject
    from app.modules.file.service import FileService
    from app.modules.identity.models import UserAccount
    from app.modules.identity.repository import IdentityRepository
    from app.modules.identity.service import CurrentUser

    web = Path("/opt/course-management/admin-web/current").resolve()
    def fetch(path):
        with urllib.request.urlopen("https://course.zsitai.xyz" + path, timeout=15) as response:
            return response.read()
    html = fetch("/").decode()
    assert html == (web / "index.html").read_text(), "Public Web release mismatch"
    for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
        assert fetch(asset) == (web / asset.lstrip("/")).read_bytes()
    manifest = json.loads((web / "PHOTO_TIME_MANIFEST.json").read_text())
    for target in manifest["renamed_imports"].values():
        source = fetch("/assets/" + target).decode()
        for previous in manifest["renamed_imports"]:
            assert previous not in source, "Mixed old/new Web module graph"
    for detail in manifest["details"]:
        bundle = fetch("/assets/" + detail["target"]).decode()
        assert "function __cmBeijingTime" in bundle
        assert bundle.count("__cmBeijingTime(") == detail["timestamp_sites"] + 1
    for endpoint in ["/api/v1/me/attendance", "/api/v1/files/1/access"]:
        try:
            fetch(endpoint)
            raise RuntimeError("Anonymous access unexpectedly allowed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    with get_session_factory()() as db:
        result = db.execute(attendance_photo_query().join(
            UserAccount, UserAccount.student_id == AttendanceRecord.student_id
        ).where(
            UserAccount.status == "ACTIVE", FileObject.status == "READY",
            (FileObject.expires_at.is_(None)) | (FileObject.expires_at > utcnow()),
        ).limit(1)).first()
        assert result is not None, "No real owned attendance scene photo available"
        record = db.get(AttendanceRecord, result.record_id)
        photo = db.get(FileObject, result.file_id)
        user = db.scalar(select(UserAccount).where(UserAccount.student_id == record.student_id))
        permissions = IdentityRepository(db).list_effective_permissions(user.id)
        actor = CurrentUser(user.id, None, "Redacted", "ACTIVE", ["STUDENT"], permissions)
        dto = AttendanceService(db)._assemble([record])[0]
        assert str(photo.id) in dto.photo_file_ids
        service = FileService(db)
        assert service.can_access(actor, photo), "Real owner authorization"
        link = service.get_access(actor, photo.id)
        assert fetch(link.url), "Real signed photo download empty"
        db.rollback()
    print(json.dumps({"public_assets_match": True, "import_graph_consistent": True,
                      "timestamp_calls": 7, "anonymous_401": True,
                      "real_owned_photo_mapping": True, "real_signed_photo_download": True}))


if __name__ == "__main__":
    {"synthetic": synthetic, "live": live}[sys.argv[1]]()
