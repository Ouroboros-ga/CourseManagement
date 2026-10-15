"""Existing mini-program snapshot calls, including an intentionally empty timetable."""

import pytest

from tests.unit.test_academic_publication import prepare, publish
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_backup_roundtrip_empty_and_owner_scope(campus):
    from app.modules.timetable.backup_service import TimetableBackupService

    db, teacher, college, _, teaching, _, _, user, other = prepare(campus)
    own = TimetableBackupService(db, user.id)
    assert own.get(teaching.semester_id)["has_backup"] is False
    value = [
        {
            "course_id": "c_test",
            "scheme_id": "s_test",
            "course_name": "Personal",
            "course_code": "",
            "color_index": 2,
            "is_custom": True,
            "teacher_name": "",
            "classroom": "A1",
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "weeks": [1, 2],
            "note": "",
            "custom_tag": "keep",
        }
    ]
    own.save(teaching.semester_id, value)
    assert own.get(teaching.semester_id)["schedule_data"] == value
    assert TimetableBackupService(db, other.id).get(teaching.semester_id)["has_backup"] is False
    own.save(teaching.semester_id, [])
    publish(db, teacher, college["id"], teaching.semester_id)
    restored = own.get(teaching.semester_id)
    assert restored["has_backup"] and restored["schedule_data"] == []
    assert restored["backup_version"] == 2
    assert restored["semester"]["id"] == str(teaching.semester_id)


def test_published_class_projection_preserves_real_dates(campus):
    from app.core.exceptions import ConflictError
    from app.modules.timetable.backup_service import TimetableBackupService

    db, teacher, college, _, teaching, _, _, user, _ = prepare(campus)
    own = TimetableBackupService(db, user.id)
    with pytest.raises(ConflictError):
        own.class_timetable(teaching.semester_id)
    publish(db, teacher, college["id"], teaching.semester_id)
    result = own.class_timetable(teaching.semester_id)
    assert result["items"] and result["items"][0]["teacher_name"] is not None
    assert result["items"][0]["weeks"]
    assert result["items"][0]["occurrence_dates"]
    assert result == own.class_timetable(teaching.semester_id)
