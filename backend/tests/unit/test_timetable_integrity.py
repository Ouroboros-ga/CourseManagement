from datetime import time

import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import CourseSchedule, CourseScheduleWeek, PeriodDefinition
from app.modules.importer.service import ImporterService
from sqlalchemy import select

from tests.unit.test_academic_publication import prepare, publisher
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


@pytest.mark.parametrize("end_period", [1, 2])
def test_publication_refuses_duplicate_active_schedule(campus, end_period):
    db, teacher, a, _, teaching, schedule, *_ = prepare(campus)
    duplicate = CourseSchedule(
        semester_id=schedule.semester_id,
        teaching_class_id=teaching.id,
        college_id=int(a["id"]),
        weekday=schedule.weekday,
        start_period=schedule.start_period,
        end_period=end_period,
        classroom=schedule.classroom,
        status="ACTIVE",
    )
    db.add(duplicate)
    db.flush()
    db.add(CourseScheduleWeek(schedule_id=duplicate.id, week_no=2))
    db.commit()
    with pytest.raises(ConflictError, match="排课重叠"):
        publisher(db, teacher, a["id"]).preview(teaching.semester_id)


def test_import_refuses_overlap_but_allows_disjoint_weeks(campus):
    db, _, _, _, _, schedule, *_ = prepare(campus)
    service = ImporterService(db)
    candidate = CourseSchedule(
        semester_id=schedule.semester_id,
        teaching_class_id=schedule.teaching_class_id,
        weekday=schedule.weekday,
        start_period=schedule.start_period,
        end_period=schedule.end_period,
        status="ACTIVE",
    )
    with pytest.raises(ConflictError, match="排课重叠"):
        service._check_schedule_overlap(candidate, [2])
    service._check_schedule_overlap(candidate, [3])
    assert candidate.id is None


def test_grid_snapshot_refuses_existing_class_timetable_even_if_times_changed(campus):
    from app.modules.academic.enrollment_models import TeachingClassAudience
    from app.modules.academic.models import AdministrativeClass

    db, _, _, _, teaching, _, student, *_ = prepare(campus)
    ac = db.get(AdministrativeClass, student.administrative_class_id)
    db.add(TeachingClassAudience(teaching_class_id=teaching.id, administrative_class_id=ac.id))
    db.commit()
    with pytest.raises(ConflictError, match="已有有效课表"):
        ImporterService(db)._check_grid_target_empty(ac, teaching.semester_id)


def test_twelve_period_school_grid_keeps_raw_period_numbers(campus):
    db, _, _, _, teaching, *_ = prepare(campus)
    existing = set(
        db.scalars(
            select(PeriodDefinition.period_no).where(
                PeriodDefinition.semester_id == teaching.semester_id
            )
        )
    )
    for number in range(1, 13):
        if number not in existing:
            db.add(
                PeriodDefinition(
                    semester_id=teaching.semester_id,
                    period_no=number,
                    start_time=time(10),
                    end_time=time(10, 45),
                )
            )
    db.commit()
    mapping = ImporterService(db).grid_slot_mapping(teaching.semester_id)
    from app.common.parsing.time_slots import parse_period

    assert parse_period("5-6节", mapping) == [5, 6]
    assert parse_period("10-11节", mapping) == [10, 11]
