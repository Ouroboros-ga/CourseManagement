"""正式教务发布和本人初始化来源，不建立可编辑的个人云端课表。"""

from datetime import time

import pytest
from app.common.pagination import PageParams
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import CourseScheduleWeek, PeriodDefinition, TeachingClassStudent
from app.modules.identity.models import UserAccount
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def publication_fixture():
    yield from campus_fixture.__wrapped__()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, schedule, student, outsider = records(db, a, b)
    db.add_all(
        [
            CourseScheduleWeek(schedule_id=schedule.id, week_no=2),
            PeriodDefinition(
                semester_id=teaching.semester_id,
                period_no=1,
                start_time=time(8),
                end_time=time(8, 45),
            ),
            PeriodDefinition(
                semester_id=teaching.semester_id,
                period_no=2,
                start_time=time(8, 55),
                end_time=time(9, 40),
            ),
            TeachingClassStudent(teaching_class_id=teaching.id, student_id=student.id),
        ]
    )
    user = UserAccount(student_id=student.id, display_name="本人", status="ACTIVE")
    other = UserAccount(student_id=outsider.id, display_name="其他学生", status="ACTIVE")
    db.add_all([user, other])
    db.commit()
    grant(config, admin, teacher, a, ["academic.manage", "academic.read"])
    return db, teacher, a, b, teaching, schedule, student, user, other


def publisher(db, actor, cid):
    from app.modules.academic.publication_service import AcademicPublicationService

    return AcademicPublicationService(db, actor, int(cid))


def publish(db, actor, cid, semester_id):
    service = publisher(db, actor, cid)
    preview = service.preview(semester_id)
    return service.publish(semester_id, preview["source_revision"])


def test_publish_is_explicit_immutable_and_same_content_is_noop(campus):
    from app.modules.academic.publication_service import MyAcademicSourceService

    db, teacher, a, _, teaching, schedule, student, user, _ = prepare(campus)
    source = MyAcademicSourceService(db, user.id)
    assert source.initialize(teaching.semester_id)["status"] == "NOT_PUBLISHED"
    first = publish(db, teacher, a["id"], teaching.semester_id)
    assert first["version"] == 1 and first["changed"]
    before = source.initialize(teaching.semester_id)
    assert before["status"] == "AVAILABLE"
    assert before["entries"][0]["source_schedule_id"] == str(schedule.id)
    assert before["entries"][0]["start_time"] == "08:00:00"
    schedule.classroom = "未发布的新地点"
    db.commit()
    assert source.initialize(teaching.semester_id) == before
    second = publish(db, teacher, a["id"], teaching.semester_id)
    assert second["version"] == 2
    assert source.initialize(teaching.semester_id)["entries"][0]["classroom"] == schedule.classroom
    repeated = publish(db, teacher, a["id"], teaching.semester_id)
    assert repeated["changed"] is False and repeated["version"] == 2
    assert source.notices(PageParams(1, 20))["total"] == 2


def test_initialization_and_notices_use_fresh_binding_and_only_own_roster(campus):
    from app.modules.academic.publication_service import MyAcademicSourceService

    db, teacher, a, _, teaching, _, student, user, other = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    source = MyAcademicSourceService(db, user.id)
    assert len(source.initialize(teaching.semester_id)["entries"]) == 1
    assert MyAcademicSourceService(db, other.id).initialize(teaching.semester_id)["entries"] == []
    assert MyAcademicSourceService(db, other.id).notices(PageParams(1, 20))["total"] == 0
    user.student_id = None
    db.commit()
    with pytest.raises(PermissionDeniedError):
        source.notices(PageParams(1, 20))


def test_removed_roster_receives_notice_but_no_stale_source_entries(campus):
    from app.modules.academic.publication_service import MyAcademicSourceService

    db, teacher, a, _, teaching, _, student, user, _ = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    row = db.scalar(
        select(TeachingClassStudent).where(TeachingClassStudent.student_id == student.id)
    )
    db.delete(row)
    db.commit()
    publish(db, teacher, a["id"], teaching.semester_id)
    source = MyAcademicSourceService(db, user.id)
    assert source.initialize(teaching.semester_id)["entries"] == []
    notices = source.notices(PageParams(1, 1))
    assert notices["total"] == 2 and len(notices["items"]) == 1
    assert "read" not in notices["items"][0] and "unread" not in notices


def test_stale_preview_and_foreign_college_write_are_rejected(campus):
    db, teacher, a, b, teaching, schedule, _, _, _ = prepare(campus)
    source = publisher(db, teacher, a["id"])
    preview = source.preview(teaching.semester_id)
    schedule.teacher = "改变后的教师"
    db.commit()
    with pytest.raises(ConflictError):
        source.publish(teaching.semester_id, preview["source_revision"])
    with pytest.raises((PermissionDeniedError, NotFoundError)) as error:
        publisher(db, teacher, b["id"]).preview(teaching.semester_id)
    assert getattr(error.value, "http_status", None) in (403, 404)


def test_http_source_and_notice_contract_no_notice_read_state(campus, monkeypatch):
    from dataclasses import replace

    from app.core.config import get_settings
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import CurrentUser
    from fastapi.testclient import TestClient

    db, teacher, a, _, teaching, _, student, user, _ = prepare(campus)
    settings = get_settings()
    monkeypatch.setattr(settings, "academic_publication_enabled", True)
    monkeypatch.setattr(settings, "campus_configuration_enabled", True)
    monkeypatch.setattr(settings, "campus_academic_scoped_enabled", True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: teacher
    with TestClient(app) as client:
        path = f"/api/v1/colleges/{a['id']}/academic/semesters/{teaching.semester_id}"
        response = client.post(path + "/publication-preview")
        assert response.status_code == 200
        assert (
            client.post(
                path + "/publish",
                json={"source_revision": response.json()["data"]["source_revision"]},
            ).status_code
            == 200
        )
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user.id, None, user.display_name, "ACTIVE", ["STUDENT"], [], pre_binding=False
        )
        initialized = client.post(
            "/api/v1/me/timetable/initialize", json={"semester_id": str(teaching.semester_id)}
        )
        assert initialized.status_code == 200
        assert initialized.json()["data"]["entries"][0]["start_time"] == "08:00:00"
        assert client.get("/api/v1/me/academic-notices").json()["data"]["total"] == 1
        assert (
            client.post(
                "/api/v1/me/timetable/initialize",
                json={"semester_id": str(teaching.semester_id), "student_id": "999"},
            ).status_code
            == 422
        )
        # 私人增删改仅通过 entries；聚合读取存在，但没有无版本整表覆盖入口。
        assert client.patch("/api/v1/me/timetable", json={}).status_code == 405
        assert (
            client.get(f"/api/v1/me/timetable?semester_id={teaching.semester_id}").json()["data"][
                "current_version"
            ]
            == 1
        )
        eid = initialized.json()["data"]["entries"][0]["id"]
        entry_path = f"/api/v1/me/timetable/entries/{eid}?semester_id={teaching.semester_id}"
        edited = client.patch(entry_path, json={"current_version": 1, "course_name": "本人名称"})
        assert edited.status_code == 200 and edited.json()["data"]["current_version"] == 2
        assert (
            client.patch(
                entry_path, json={"current_version": 1, "course_name": "旧设备"}
            ).status_code
            == 409
        )
        assert (
            client.request("DELETE", entry_path, json={"current_version": 2}).json()["data"][
                "entries"
            ]
            == []
        )
        assert client.post("/api/v1/me/academic-notices/1/read").status_code == 404
        monkeypatch.setattr(settings, "academic_publication_enabled", False)
        assert client.get("/api/v1/me/academic-notices").status_code == 503
        monkeypatch.setattr(settings, "academic_publication_enabled", True)
        app.dependency_overrides[get_current_user] = lambda: replace(teacher, pre_binding=True)
        assert client.get("/api/v1/me/academic-notices").status_code == 403


def test_missing_times_cannot_publish(campus):
    from app.core.exceptions import AppError

    _, _, _, teacher, a, _ = campus
    db, _, _, _, teaching, _, _, _, _ = prepare(campus)
    period = db.scalar(select(PeriodDefinition).where(PeriodDefinition.period_no == 1))
    period.start_time = None
    db.commit()
    with pytest.raises(AppError) as error:
        publisher(db, teacher, a["id"]).preview(teaching.semester_id)
    assert error.value.http_status == 422


def test_published_source_uses_explicit_common_class_audience(campus):
    from app.modules.academic.enrollment_models import TeachingClassAudience
    from app.modules.academic.publication_service import MyAcademicSourceService

    db, teacher, a, _, teaching, _, student, user, other = prepare(campus)
    for row in db.scalars(select(TeachingClassStudent)):
        db.delete(row)
    db.add(
        TeachingClassAudience(
            teaching_class_id=teaching.id, administrative_class_id=student.administrative_class_id
        )
    )
    db.commit()
    publish(db, teacher, a["id"], teaching.semester_id)
    assert (
        len(MyAcademicSourceService(db, user.id).initialize(teaching.semester_id)["entries"]) == 1
    )
    assert MyAcademicSourceService(db, other.id).initialize(teaching.semester_id)["entries"] == []
