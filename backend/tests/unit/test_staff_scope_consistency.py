"""合班任务的本人读取范围，以及换教室后的真实目的地回归。"""

from contextlib import contextmanager
from io import BytesIO

import openpyxl
import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import CourseSchedule, Semester, TeachingClass
from app.modules.academic.occurrence_location_models import (
    OccurrenceLocationChange,
    OccurrenceLocationOverride,
)
from app.modules.inspection.models import InspectionTask, TaskRosterMemberClass, TaskScheduleSource
from app.modules.inspection.staff_record_query import TeachingScope
from sqlalchemy import select

from tests.unit import test_occurrence_location as loc
from tests.unit import test_staff_corrections as corr


@pytest.fixture
def merged():
    with contextmanager(corr.correction_db.__wrapped__)() as db:
        corr.add_relation(db, local_class=1)
        corr.make_merged_task(db, provenance=True)
        db.get(InspectionTask, 3).course_name_snapshot = "SCOPE-REGRESSION"
        db.commit()
        query, _ = corr._query(db)
        yield db, query


def test_summary_counts_the_same_authorized_students_as_card(merged):
    _, query = merged
    assert query.get_card(3, "teaching").counts.total == 1
    summary = query.get_summary("teaching", course_name="SCOPE-REGRESSION")
    assert summary.student_counts.total == 1


def test_export_excludes_foreign_student_hidden_from_detail(merged):
    _, query = merged
    rows, total = query.list_attendance(3, "teaching", None, corr.page_params(1, 50))
    assert total == 1 and [r.student_no for r in rows] == ["S001"]
    data, _ = query.export_excel("teaching", course_name="SCOPE-REGRESSION")
    workbook = openpyxl.load_workbook(BytesIO(data), read_only=True)
    values = [value for row in workbook.active.iter_rows(values_only=True) for value in row]
    workbook.close()
    assert "S001" in values
    assert "S002" not in values


def test_batch_scope_does_not_mix_roster_versions(merged):
    db, _ = merged
    task = db.get(InspectionTask, 3)
    task.roster_version = 2
    db.add_all([
        TaskRosterMemberClass(task_id=3, roster_version=2, student_id=1, teaching_class_id=2),
        TaskRosterMemberClass(task_id=3, roster_version=2, student_id=2, teaching_class_id=1),
    ])
    db.commit()
    scope = TeachingScope(db, [task], 1, corr.COURSE_DAY)
    assert not scope.visible(3, 1)
    assert scope.correctable(3, 2)


@pytest.fixture
def independent_courses():
    with contextmanager(loc.location_db.__wrapped__)() as db:
        loc.add_relation(db)
        for teaching in db.scalars(select(TeachingClass)):
            teaching.academic_offering_id = None
        for schedule in db.scalars(select(CourseSchedule)):
            schedule.shared_meeting_key = None
            schedule.shared_identity_from = None
            schedule.classroom = "A101"
        db.commit()
        yield db


def test_existing_merged_task_refuses_partial_room_move_atomically(independent_courses):
    db = independent_courses
    task = InspectionTask(
        task_key="MERGED-ROOM", semester_id=1, inspection_date=loc.COURSE_DAY,
        week_no=6, inspection_type="COURSE", start_period=1, end_period=2,
        teaching_class_id=1, course_schedule_id=1, college_id=1,
        occurrence_keys_snapshot=[loc.KEY, "s:2|2026-10-07"], classroom_snapshot="A101",
    )
    db.add(task)
    db.flush()
    task_id = task.id
    db.add_all([TaskScheduleSource(task_id=task_id, teaching_class_id=i, course_schedule_id=i)
                for i in (1, 2)])
    db.commit()
    with pytest.raises(ConflictError, match="拆分"):
        loc.service(db).change_location(loc.staff_ref(db), 1, loc.KEY, loc.occurrence_request())
    db.expire_all()
    assert db.get(InspectionTask, task_id).classroom_snapshot == "A101"
    assert not list(db.scalars(select(OccurrenceLocationOverride)))
    assert not list(db.scalars(select(OccurrenceLocationChange)))


def test_future_plan_groups_by_effective_room_before_merging(independent_courses):
    from app.modules.inspection.schemas import InspectionGenerateRequest
    from app.modules.inspection.service import InspectionService

    db = independent_courses
    loc.service(db).change_location(loc.staff_ref(db), 1, loc.KEY, loc.occurrence_request())
    planner = InspectionService(db)
    body = InspectionGenerateRequest(
        semester_id=1, inspection_type="COURSE", date_from=loc.COURSE_DAY,
        date_to=loc.COURSE_DAY, teaching_class_ids=[1, 2],
    )
    items = planner._build_course_plan_core(db.get(Semester, 1), body)
    assert len(items) == 2
    destinations = {key: item.classroom_snapshot for item in items for key in item.occurrence_keys}
    assert destinations == {loc.KEY: "B202", "s:2|2026-10-07": "A101"}


def test_shared_plan_keeps_task_identity_after_room_change(independent_courses):
    from app.modules.inspection.schemas import InspectionGenerateRequest
    from app.modules.inspection.service import InspectionService

    db = independent_courses
    for schedule in db.scalars(select(CourseSchedule)):
        schedule.shared_meeting_key = "s:1"
        schedule.shared_identity_from = loc.COURSE_DAY
    db.commit()
    planner = InspectionService(db)
    body = InspectionGenerateRequest(
        semester_id=1, inspection_type="COURSE", date_from=loc.COURSE_DAY,
        date_to=loc.COURSE_DAY, teaching_class_ids=[1, 2],
    )
    before = planner._build_course_plan_core(db.get(Semester, 1), body)
    loc.service(db).change_location(loc.staff_ref(db), 1, loc.KEY, loc.occurrence_request())
    after = planner._build_course_plan_core(db.get(Semester, 1), body)
    assert len(before) == len(after) == 1
    assert after[0].classroom_snapshot == "B202"
    assert after[0].task_key == before[0].task_key


def test_legacy_plan_override_refuses_independent_occurrence_keys(independent_courses):
    from app.modules.academic.occurrence_location import apply_course_plan_overrides
    from app.modules.inspection.service import PlanItem

    db = independent_courses
    loc.service(db).change_location(loc.staff_ref(db), 1, loc.KEY, loc.occurrence_request())
    item = PlanItem(
        task_key="MERGED", semester_id=1, inspection_date=loc.COURSE_DAY, week_no=6,
        inspection_type="COURSE", start_period=1, end_period=2, course_schedule_id=1,
        teaching_class_id=1, administrative_class_id=None, course_name_snapshot="数学",
        class_name_snapshot="合班", classroom_snapshot="A101", require_photo_snapshot=False,
        occurrence_keys=[loc.KEY, "s:2|2026-10-07"],
    )
    with pytest.raises(ConflictError, match="分组"):
        apply_course_plan_overrides(db, [item])
    assert item.classroom_snapshot == "A101"
