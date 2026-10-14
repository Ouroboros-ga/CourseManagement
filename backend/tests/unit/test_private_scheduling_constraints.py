"""Unclassified legacy workload remains blocking, without exposing other students."""

from datetime import date
import pytest

from app.modules.academic.models import (
    CourseSchedule,
    CourseScheduleWeek,
)
from app.modules.identity.query_scope import activate_query_scope
from app.modules.inspection.models import InspectionAssignment, InspectionTask
from app.modules.inspection.scheduling.private_constraints import (
    assignment_loads,
    assignment_times,
    course_times,
)
from sqlalchemy import select

from tests.unit.test_enrollment_lifecycle import add_courses, school as original_school


@pytest.fixture
def school():
    from app.modules.identity.query_scope import ScopedSession
    generator = original_school.__wrapped__()
    original = next(generator)
    try:
        with ScopedSession(original.get_bind(), expire_on_commit=False) as scoped:
            yield scoped
    finally:
        generator.close()


def test_subject_time_constraints_include_unclassified_legacy_roots(school):  # noqa: F811
    add_courses(school)
    school.add(
        CourseSchedule(
            id=100,
            semester_id=1,
            teaching_class_id=3,
            weekday=1,
            start_period=3,
            end_period=4,
            college_id=None,
        )
    )
    school.flush()
    school.add(CourseScheduleWeek(schedule_id=100, week_no=1))
    school.add(
        InspectionTask(
            id=100,
            task_key="legacy-time",
            semester_id=1,
            inspection_date=date(2026, 10, 19),
            week_no=1,
            inspection_type="COURSE",
            start_period=3,
            end_period=4,
            college_id=None,
        )
    )
    school.flush()
    school.add(InspectionAssignment(task_id=100, volunteer_user_id=3, assign_method="MANUAL"))
    school.commit()
    activate_query_scope(school, 2)
    assert school.scalar(select(InspectionTask).where(InspectionTask.id == 100)) is None
    assert course_times(school, 1, [1], {date(2026, 10, 19): (1, 1)})[1, date(2026, 10, 19)] == [
        (3, 4)
    ]
    assert assignment_times(school, [3], {date(2026, 10, 19)})[0][1].id == 100
    assert assignment_loads(school, 1, [3]) == {3: 1}
    assert assignment_times(school, [2], {date(2026, 10, 19)}) == []
