from datetime import date, time

import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import (
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    TeachingClass,
)
from app.modules.academic.offerings import OfferingService, assert_shared_consistent

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_matching_is_only_a_recommendation_and_confirmed_identity_keeps_views_separate(campus):
    _, db, admin, _, a, b = campus
    semester = Semester(
        code="2026-F",
        name="秋季",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 31),
        first_monday=date(2026, 8, 31),
        total_weeks=22,
    )
    db.add(semester)
    db.flush()
    from app.modules.academic.models import PeriodDefinition

    db.add_all(
        [
            PeriodDefinition(
                semester_id=semester.id, period_no=1, start_time=time(8), end_time=time(8, 45)
            ),
            PeriodDefinition(
                semester_id=semester.id, period_no=2, start_time=time(8, 55), end_time=time(9, 40)
            ),
        ]
    )
    views = []
    for college in (a, b):
        course = Course(college_id=int(college["id"]), course_code="MATH", course_name="高等数学")
        db.add(course)
        db.flush()
        teaching = TeachingClass(
            college_id=int(college["id"]),
            semester_id=semester.id,
            course_id=course.id,
            class_code="1",
            class_name="数学教学班",
            teacher_name="李老师",
        )
        db.add(teaching)
        db.flush()
        schedule = CourseSchedule(
            college_id=teaching.college_id,
            semester_id=semester.id,
            teaching_class_id=teaching.id,
            weekday=1,
            start_period=1,
            end_period=2,
            classroom="A101",
        )
        db.add(schedule)
        db.flush()
        db.add(CourseScheduleWeek(schedule_id=schedule.id, week_no=10))
        views.append((teaching, schedule))
    db.commit()
    own, target = views[0][0], views[1][0]
    service = OfferingService(db, admin, int(a["id"]), own.id)
    candidates = service.candidates()
    assert candidates["items"][0]["teaching_class_id"] == str(target.id)
    assert own.academic_offering_id is None and target.academic_offering_id is None
    body = {"target_teaching_class_id": str(target.id), "reason": "老师确认同一公共课教学班"}
    preview = service.preview(body)
    result = service.confirm({**body, "revision": preview["revision"]})
    assert own.academic_offering_id == target.academic_offering_id == result["academic_offering_id"]
    assert own.college_id != target.college_id and not result["student_rosters_shared"]
    assert views[0][1].shared_meeting_key == views[1][1].shared_meeting_key
    assert_shared_consistent(db, own.id)
    views[1][1].classroom = "B201"
    db.commit()
    with pytest.raises(ConflictError, match="来源冲突"):
        assert_shared_consistent(db, own.id)
