"""云端私人副本：本人最后保存优先，发布、绑定、排班都不能覆盖它。"""

import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.models import CourseSchedule
from sqlalchemy import select

from tests.unit.test_academic_publication import prepare, publish
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def personal_fixture():
    yield from campus_fixture.__wrapped__()


def personal(db, user_id):
    from app.modules.timetable.service import PersonalTimetableService

    return PersonalTimetableService(db, user_id)


def test_initialize_once_and_personal_edit_survives_official_updates(campus):
    db, teacher, a, _, teaching, schedule, _, user, _ = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    own = personal(db, user.id)
    initialized = own.initialize(teaching.semester_id)
    entry = initialized["entries"][0]
    official = db.scalar(select(CourseSchedule).where(CourseSchedule.id == schedule.id))
    updated = own.update_entry(
        teaching.semester_id, entry["id"], {"current_version": 1, "classroom": "本人备注地点"}
    )
    assert updated["current_version"] == 2
    assert official.classroom != "本人备注地点"
    official.classroom = "教务新地点"
    db.commit()
    publish(db, teacher, a["id"], teaching.semester_id)
    assert own.initialize(teaching.semester_id) == updated
    assert own.get(teaching.semester_id)["entries"][0]["classroom"] == "本人备注地点"
    with pytest.raises(ConflictError):
        own.update_entry(
            teaching.semester_id, entry["id"], {"current_version": 1, "classroom": "过期设备写入"}
        )


def test_deleted_empty_timetable_is_not_reinitialized_and_manual_course_is_private(campus):
    db, teacher, a, _, teaching, _, _, user, _ = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    own = personal(db, user.id)
    value = own.initialize(teaching.semester_id)
    empty = own.delete_entry(teaching.semester_id, value["entries"][0]["id"], 1)
    assert empty["entries"] == [] and own.initialize(teaching.semester_id) == empty
    added = own.create_entry(
        teaching.semester_id,
        {
            "current_version": 2,
            "course_name": "本人选修",
            "weekday": 1,
            "week_nos": [1, 2],
            "start_time": "07:00:00",
            "end_time": "07:30:00",
        },
    )
    assert added["current_version"] == 3
    assert added["entries"][0]["source_schedule_id"] is None


def test_fresh_binding_and_student_status_protect_cached_personal_service(campus):
    db, teacher, a, _, teaching, _, student, user, other = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    own = personal(db, user.id)
    own.initialize(teaching.semester_id)
    assert personal(db, other.id).get(teaching.semester_id)["status"] == "NOT_INITIALIZED"
    user.student_id = None
    db.commit()
    with pytest.raises(PermissionDeniedError):
        own.get(teaching.semester_id)


def test_semester_choices_are_own_published_or_initialized_and_no_foreign_records(campus):
    db, teacher, a, _, teaching, _, _, user, other = prepare(campus)
    assert personal(db, user.id).semesters() == []
    publish(db, teacher, a["id"], teaching.semester_id)
    choices = personal(db, user.id).semesters()
    assert choices[0]["id"] == str(teaching.semester_id)
    assert choices[0]["initialized"] is False
    personal(db, user.id).initialize(teaching.semester_id)
    assert personal(db, user.id).semesters()[0]["initialized"] is True
    assert personal(db, other.id).semesters() == []


def test_personal_http_crud_version_and_owner_boundary(campus, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import CurrentUser
    from fastapi.testclient import TestClient

    db, teacher, a, _, teaching, _, _, user, other = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    monkeypatch.setattr(get_settings(), "academic_publication_enabled", True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    actor = CurrentUser(
        user.id, None, user.display_name, "ACTIVE", ["STUDENT"], [], pre_binding=False
    )
    app.dependency_overrides[get_current_user] = lambda: actor
    base = f"/api/v1/me/timetable"
    query = f"?semester_id={teaching.semester_id}"
    with TestClient(app) as client:
        assert client.get(base + query).json()["data"]["status"] == "NOT_INITIALIZED"
        initial = client.post(base + "/initialize", json={"semester_id": str(teaching.semester_id)})
        assert initial.status_code == 200
        assert initial.json()["data"]["current_version"] == 1
        created = client.post(
            base + "/entries" + query,
            json={
                "current_version": 1,
                "course_name": "个人选修",
                "weekday": 3,
                "week_nos": [1, 2],
                "start_time": "18:00:00",
                "end_time": "19:00:00",
            },
        )
        assert created.status_code == 200
        entry = created.json()["data"]["entries"][-1]
        target = base + "/entries/" + entry["id"] + query
        assert (
            client.patch(target, json={"current_version": 1, "note": "旧版本"}).status_code == 409
        )
        edited = client.patch(target, json={"current_version": 2, "note": "私人备注"})
        assert edited.status_code == 200
        assert edited.json()["data"]["current_version"] == 3
        deleted = client.request("DELETE", target, json={"current_version": 3})
        assert deleted.status_code == 200
        assert all(row["id"] != entry["id"] for row in deleted.json()["data"]["entries"])
        actor = CurrentUser(
            other.id, None, other.display_name, "ACTIVE", ["STUDENT"], [], pre_binding=False
        )
        assert client.get(base + query).json()["data"]["status"] == "NOT_INITIALIZED"
        assert client.patch(target, json={"current_version": 4, "note": "越权"}).status_code == 409


def test_personal_custom_fields_and_periods(campus):
    db, teacher, a, _, teaching, _, _, user, _ = prepare(campus)
    publish(db, teacher, a["id"], teaching.semester_id)
    own = personal(db, user.id)
    val = own.initialize(teaching.semester_id)
    entry_id = val["entries"][0]["id"]
    updated = own.update_entry(
        teaching.semester_id,
        entry_id,
        {
            "current_version": 1,
            "start_period": 3,
            "end_period": 4,
            "color": "#4F46E5",
            "custom_tag": "重点复习",
        },
    )
    assert updated["current_version"] == 2
    saved_entry = next(e for e in updated["entries"] if e["id"] == entry_id)
    assert saved_entry["start_period"] == 3
    assert saved_entry["end_period"] == 4
    assert saved_entry["color"] == "#4F46E5"
    assert saved_entry.get("custom_tag") == "重点复习"

