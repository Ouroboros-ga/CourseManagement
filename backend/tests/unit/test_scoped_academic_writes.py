import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.scoped_writes import ScopedAcademicWriteService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def prepare(campus):
    config, db, admin, teacher, a, b = campus
    rows = records(db, a, b)
    grant(config, admin, teacher, a, ["academic.manage", "academic.read", "student.manage"])
    return ScopedAcademicWriteService(db, teacher, int(a["id"])), rows


def test_scoped_create_edit_and_stale_version(campus):
    service, rows = prepare(campus)
    course = service.create("courses", {"course_code": "A-NEW", "course_name": "学院课程"})
    teaching = service.create(
        "teaching_classes",
        {"semester_id": rows[3].semester_id, "course_id": course["id"], "class_name": "学院教学班"},
    )
    schedule = service.create(
        "schedules",
        {
            "teaching_class_id": teaching["id"],
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "weeks": [2],
        },
    )
    assert schedule["college_id"] == campus[4]["id"]
    updated = service.update(
        "schedules",
        int(schedule["id"]),
        {"ownership_version": schedule["ownership_version"], "classroom": "本院新教室"},
    )
    assert updated["classroom"] == "本院新教室"
    with pytest.raises(ConflictError):
        service.update(
            "schedules",
            int(schedule["id"]),
            {"ownership_version": schedule["ownership_version"], "classroom": "陈旧修改"},
        )


def test_foreign_parent_and_shared_course_write_are_rejected(campus):
    service, rows = prepare(campus)
    with pytest.raises(NotFoundError):
        service.create(
            "students",
            {"student_no": "NEW", "name": "新学生", "administrative_class_id": rows[1].id},
        )
    with pytest.raises(NotFoundError):
        service.update(
            "courses",
            rows[3].course_id,
            {"ownership_version": 1, "course_name": "不能修改学校共享课程"},
        )


def test_mixed_delete_has_no_partial_write(campus):
    service, rows = prepare(campus)
    one = service.create("courses", {"course_code": "A-UNUSED", "course_name": "待删除"})
    with pytest.raises(NotFoundError):
        service.delete_many("courses", [int(one["id"]), 999999], {int(one["id"]): 1, 999999: 1})
    assert service.get_row("courses", int(one["id"]))["id"] == one["id"]
    result = service.delete_many("courses", [int(one["id"])], {int(one["id"]): 1})
    assert result["deleted_ids"] == [one["id"]]
