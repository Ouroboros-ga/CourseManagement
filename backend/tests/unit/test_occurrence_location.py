"""教师指定真实课次换教室：版本链、范围、共享映射与任务目的地联动（T04）。"""

from datetime import date

import pytest
from app.models import Base
from app.modules.academic.models import (
    AdministrativeClass,
    CalendarOverride,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    Semester,
    Student,
    TeachingClass,
)
from app.modules.academic.occurrence_location_models import (
    OccurrenceLocationChange,
    OccurrenceLocationOverride,
)
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import FacultyStaff, TeachingStaffAssignment
from app.modules.identity.models import UserAccount
from app.modules.inspection.models import InspectionTask
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

COURSE_DAY = date(2026, 10, 7)
KEY = "s:1|2026-10-07"


def occurrence_request(**kwargs):
    from app.modules.academic.occurrence_location import OccurrenceLocationRequest

    defaults = {"location": "B202", "revision": 0}
    defaults.update(kwargs)
    return OccurrenceLocationRequest(**defaults)


@pytest.fixture(name="db")
def location_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all([College(id=i, school_id=1, code=str(i), name=str(i)) for i in (1, 2)])
        db.add(UserAccount(id=1, display_name="教师", status="ACTIVE"))
        db.add(
            Semester(
                id=1,
                code="F",
                name="秋",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 31),
                first_monday=date(2026, 8, 31),
                total_weeks=22,
            )
        )
        db.flush()
        db.add(AcademicOffering(id="shared", school_id=1, semester_id=1, course_name="数学"))
        db.add(Course(id=1, college_id=1, course_code="M1", course_name="数学"))
        db.add(Course(id=2, college_id=2, course_code="M2", course_name="数学"))
        db.flush()
        db.add(
            TeachingClass(
                id=1, college_id=1, semester_id=1, course_id=1, class_code="1",
                class_name="数学一班", academic_offering_id="shared",
            )
        )
        db.add(
            TeachingClass(
                id=2, college_id=2, semester_id=1, course_id=2, class_code="2",
                class_name="数学二班", academic_offering_id="shared",
            )
        )
        db.add(AdministrativeClass(id=1, college_id=1, class_code="A", class_name="一班"))
        db.flush()
        db.add(Student(id=1, student_no="S001", name="张一", administrative_class_id=1))
        db.add(FacultyStaff(school_id=1, college_id=1, staff_no="T001", name="教师", user_id=1))
        db.flush()
        db.add(
            CourseSchedule(
                id=1, teaching_class_id=1, semester_id=1, college_id=1, weekday=3,
                start_period=1, end_period=2, classroom="A101",
                shared_meeting_key="s:1", shared_identity_from=date(2026, 9, 1),
            )
        )
        db.add_all([CourseScheduleWeek(schedule_id=1, week_no=6)])
        db.add(
            CourseSchedule(
                id=2, teaching_class_id=2, semester_id=1, college_id=2, weekday=3,
                start_period=1, end_period=2, classroom="A102",
                shared_meeting_key="s:1", shared_identity_from=date(2026, 9, 1),
            )
        )
        db.add_all([CourseScheduleWeek(schedule_id=2, week_no=6)])
        db.commit()
        yield db
    engine.dispose()


def add_relation(db, *, local_class=1):
    db.add(
        TeachingStaffAssignment(
            staff_id=1,
            semester_id=1,
            anchor_type="LOCAL",
            teaching_class_id=local_class,
            effective_from=date(2026, 9, 1),
        )
    )
    db.commit()


def staff_ref(db):
    from app.modules.identity.service import CurrentUser
    from app.modules.identity.staff_deps import CurrentStaff

    row = db.scalar(select(FacultyStaff))
    return CurrentStaff(
        user=CurrentUser(
            id=row.user_id,
            username=None,
            display_name=row.name,
            status="ACTIVE",
            roles=[],
            permissions=[],
        ),
        staff_id=row.id,
        staff_no=row.staff_no,
        name=row.name,
        school_id=row.school_id,
        college_id=row.college_id,
        lock_version=row.lock_version,
    )


def service(db):
    from app.modules.academic.occurrence_location import OccurrenceLocationService

    return OccurrenceLocationService(db)


def make_task(db, *, key, snapshot=None, canceled=False, semester_id=1,
              with_source=False, with_submission=False, with_record=False):
    from app.core.database import utcnow
    from app.modules.inspection.models import (
        InspectionSubmission,
        ReviewStatus,
        TaskScheduleSource,
    )

    task = InspectionTask(
        task_key=key,
        semester_id=semester_id,
        inspection_date=COURSE_DAY,
        week_no=6,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        teaching_class_id=1,
        college_id=1,
        classroom_snapshot="A101",
        roster_version=1,
        occurrence_keys_snapshot=snapshot,
    )
    if canceled:
        task.canceled_at = utcnow()
        task.canceled_by = 1
    db.add(task)
    db.flush()
    if with_source:
        db.add(TaskScheduleSource(task_id=task.id, course_schedule_id=1, teaching_class_id=1))
    if with_submission:
        db.add(
            InspectionSubmission(
                task_id=task.id,
                attempt_no=1,
                volunteer_user_id=1,
                roster_version=1,
                result="NORMAL",
                review_status=ReviewStatus.APPROVED.value,
                submitted_at=utcnow(),
            )
        )
    if with_record:
        from app.modules.attendance.models import AttendanceRecord

        db.add(
            AttendanceRecord(
                task_id=task.id, student_id=1, effective_type="NORMAL", current_version=1
            )
        )
    db.commit()
    return task


def test_change_updates_override_chain_revision_and_unfinished_destination(db):
    add_relation(db)
    first = make_task(db, key="PA", snapshot=[KEY], with_source=True)
    # 两条任务引用同一真实课次可联动；含独立课次的任务另有原子拒绝回归。
    second = make_task(db, key="FA", snapshot=[KEY], with_source=True)
    summary = service(db).change_location(
        staff_ref(db), 1, KEY, occurrence_request(revision=0, reason="换教室"), "REQ-1"
    )
    assert summary.occurrence_key == KEY
    assert summary.base_location == "A101"
    assert summary.current_location == "B202" and summary.overridden and summary.revision == 1
    affected_ids = [str(t.id) for t in sorted((first, second), key=lambda t: t.id)]
    assert summary.affected_task_ids == affected_ids
    assert first.classroom_snapshot == "B202" and second.classroom_snapshot == "B202"
    row = db.scalar(select(OccurrenceLocationOverride))
    assert row.occurrence_key == KEY and row.location == "B202" and row.revision == 1
    changes = db.scalars(select(OccurrenceLocationChange)).all()
    assert [(c.revision_no, c.previous_location, c.new_location) for c in changes] == [
        (1, None, "B202")
    ]


def test_get_summary_reflects_override_and_base(db):
    add_relation(db)
    make_task(db, key="PA", with_source=True)
    before = service(db).location_summary(staff_ref(db), 1, KEY)
    assert before.base_location == "A101"
    assert before.current_location == "A101" and not before.overridden and before.revision == 0
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    after = service(db).location_summary(staff_ref(db), 1, KEY)
    assert after.current_location == "B202" and after.overridden and after.revision == 1


def test_request_requires_the_seen_revision():
    """省略所见版本即跳过乐观校验，会让旧页面静默覆盖他人已保存的安排；契约要求必传。"""
    from app.modules.academic.occurrence_location import OccurrenceLocationRequest
    from pydantic import ValidationError

    for payload in ({"location": "C303"}, {"location": "C303", "revision": None}):
        with pytest.raises(ValidationError):
            OccurrenceLocationRequest.model_validate(payload)
    saved = OccurrenceLocationRequest.model_validate({"location": "C303", "revision": 0})
    assert saved.revision == 0


def test_makeup_day_resolves_the_source_weekday_occurrence(db):
    """调补课（周六补第 6 周周三的课）必须按校历找到那节课，否则教师既看不到也改不了地点。"""
    add_relation(db)
    makeup_day = date(2026, 10, 10)
    key = f"s:1|{makeup_day}"
    db.add(
        CalendarOverride(
            semester_id=1, date=makeup_day, override_type="MAKEUP",
            source_teaching_week=6, source_teaching_weekday=3,
        )
    )
    db.commit()
    summary = service(db).location_summary(staff_ref(db), 1, key)
    assert summary.base_location == "A101" and summary.revision == 0
    changed = service(db).change_location(
        staff_ref(db), 1, key, occurrence_request(revision=0, reason="调补课换教室"), "REQ-M"
    )
    assert changed.current_location == "B202" and changed.revision == 1
    db.expire_all()
    row = db.scalar(
        select(OccurrenceLocationOverride).where(OccurrenceLocationOverride.occurrence_key == key)
    )
    assert row is not None and row.location == "B202"


def test_stop_day_offers_no_modifiable_occurrence(db):
    """停课日不伪造一个可改地点的课次。"""
    from app.core.exceptions import NotFoundError

    add_relation(db)
    db.add(CalendarOverride(semester_id=1, date=COURSE_DAY, override_type="STOP"))
    db.commit()
    with pytest.raises(NotFoundError):
        service(db).location_summary(staff_ref(db), 1, KEY)


def test_stale_revision_conflicts_and_writes_nothing(db):
    from app.core.exceptions import ConflictError, ErrorCode

    add_relation(db)
    make_task(db, key="PA", with_source=True)
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(revision=0), None)
    with pytest.raises(ConflictError) as exc:
        service(db).change_location(
            staff_ref(db), 1, KEY, occurrence_request(location="C303", revision=0), None
        )
    assert exc.value.code == ErrorCode.VERSION_CONFLICT
    row = db.scalar(select(OccurrenceLocationOverride))
    assert row.location == "B202" and row.revision == 1
    assert db.scalars(select(OccurrenceLocationChange)).all() != []


def test_restore_keeps_history_and_tasks_return_to_base(db):
    add_relation(db)
    task = make_task(db, key="PA", with_source=True)
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    summary = service(db).change_location(
        staff_ref(db), 1, KEY, occurrence_request(location=None, revision=1), None
    )
    assert summary.overridden is False and summary.revision == 2
    assert summary.current_location == "A101" and summary.base_location == "A101"
    assert task.classroom_snapshot == "A101"
    changes = db.scalars(
        select(OccurrenceLocationChange).order_by(OccurrenceLocationChange.id)
    ).all()
    assert [(c.revision_no, c.new_location) for c in changes] == [(1, "B202"), (2, None)]


def test_foreign_class_or_absent_occurrence_is_not_found(db):
    from app.core.exceptions import NotFoundError

    add_relation(db)
    svc = service(db)
    # 非法课次键、他人教学班、本人无课日期统一 404，防枚举。
    with pytest.raises(NotFoundError):
        svc.location_summary(staff_ref(db), 1, "bogus")
    with pytest.raises(NotFoundError):
        svc.location_summary(staff_ref(db), 1, "s:1|2026-02-30")
    with pytest.raises(NotFoundError):
        svc.location_summary(staff_ref(db), 2, KEY)
    with pytest.raises(NotFoundError):
        service(db).change_location(staff_ref(db), 2, KEY, occurrence_request(), None)
    # 本人教学班但该周没有这节课（第 7 周）。
    with pytest.raises(NotFoundError):
        svc.location_summary(staff_ref(db), 1, "s:1|2026-10-14")


def test_shared_mapping_shape_conflict_blocks_change(db):
    from app.core.exceptions import ConflictError, ErrorCode

    add_relation(db)
    # 同一共享课次在两个学院视图的节次不一致：必须先核对映射，不能只按本人视图改教室。
    db.add(
        CourseSchedule(
            id=3, teaching_class_id=1, semester_id=1, college_id=1, weekday=3,
            start_period=3, end_period=4, classroom="A103",
            shared_meeting_key="s:1", shared_identity_from=date(2026, 9, 1),
        )
    )
    db.add_all([CourseScheduleWeek(schedule_id=3, week_no=6)])
    db.commit()
    with pytest.raises(ConflictError) as exc:
        service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    assert exc.value.code == ErrorCode.STATE_CONFLICT
    assert db.scalar(select(OccurrenceLocationOverride)) is None


def test_unfinished_destinations_update_completed_or_canceled_keep_snapshot(db):
    add_relation(db)
    fresh = make_task(db, key="FA", snapshot=[KEY], with_source=True)
    legacy = make_task(db, key="LG", snapshot=None, with_source=True)
    canceled = make_task(db, key="CA", snapshot=[KEY], canceled=True)
    settled = make_task(
        db, key="SA", snapshot=[KEY], with_submission=True
    )
    attended = make_task(
        db, key="RA", snapshot=[KEY], with_record=True
    )
    summary = service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    affected = {int(x) for x in summary.affected_task_ids}
    assert affected == {fresh.id, legacy.id}
    assert fresh.classroom_snapshot == "B202"
    assert legacy.classroom_snapshot == "B202"
    assert canceled.classroom_snapshot == "A101"
    assert settled.classroom_snapshot == "A101"
    assert attended.classroom_snapshot == "A101"


def test_archived_semester_blocks_write_but_chain_and_read_remain(db):
    from app.core.exceptions import ConflictError

    add_relation(db)
    make_task(db, key="PA", with_source=True)
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    db.execute(Semester.__table__.update().values(status="ARCHIVED"))
    db.commit()
    with pytest.raises(ConflictError):
        service(db).change_location(
            staff_ref(db), 1, KEY, occurrence_request(location="C303", revision=1), None
        )
    summary = service(db).location_summary(staff_ref(db), 1, KEY)
    assert summary.current_location == "B202" and summary.revision == 1


def test_plan_generation_consumes_override_and_selection_summary(db):
    from app.modules.academic.occurrence_location import (
        apply_course_plan_overrides,
        selection_summary_terms,
    )
    from app.modules.inspection.service import PlanItem

    add_relation(db)
    make_task(db, key="PA", with_source=True)
    item_a = PlanItem(
        task_key="K1", semester_id=1, inspection_date=COURSE_DAY, week_no=6,
        inspection_type="COURSE", start_period=1, end_period=2,
        course_schedule_id=1, teaching_class_id=1, administrative_class_id=None,
        course_name_snapshot="数学", class_name_snapshot="数学一班",
        classroom_snapshot="A101", require_photo_snapshot=False,
        occurrence_keys=[KEY],
    )
    summary = service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    assert summary.revision == 1
    apply_course_plan_overrides(db, [item_a])
    assert item_a.classroom_snapshot == "B202"
    keys = {KEY, "s:9|2026-10-08"}
    assert selection_summary_terms(db, keys) == [(KEY, 1), ("s:9|2026-10-08", 0)]
    item_b = PlanItem(
        task_key="K2", semester_id=1, inspection_date=COURSE_DAY, week_no=6,
        inspection_type="COURSE", start_period=1, end_period=2,
        course_schedule_id=1, teaching_class_id=1, administrative_class_id=None,
        course_name_snapshot="数学", class_name_snapshot="数学一班",
        classroom_snapshot="A101", require_photo_snapshot=False,
        occurrence_keys=["s:9|2026-10-09"],
    )
    apply_course_plan_overrides(db, [item_b])
    # 无覆盖键的计划保持课表原地点。
    assert item_b.classroom_snapshot == "A101"
    db.execute(OccurrenceLocationOverride.__table__.update().values(location=None))
    db.commit()
    # 恢复原始地点后不再有生效覆盖；生成计划每次重建条目，取回课表原地点。
    item_restored = PlanItem(
        task_key="K3", semester_id=1, inspection_date=COURSE_DAY, week_no=6,
        inspection_type="COURSE", start_period=1, end_period=2,
        course_schedule_id=1, teaching_class_id=1, administrative_class_id=None,
        course_name_snapshot="数学", class_name_snapshot="数学一班",
        classroom_snapshot="A101", require_photo_snapshot=False,
        occurrence_keys=[KEY],
    )
    apply_course_plan_overrides(db, [item_restored])
    assert item_restored.classroom_snapshot == "A101"


# --------------------------------------------------------------------------- #
# 事务边界：换教室必须由写服务单次提交，请求会话关闭后仍可见
# --------------------------------------------------------------------------- #
def test_change_location_commits_once(db):
    from sqlalchemy import event

    add_relation(db)
    make_task(db, key="PA", snapshot=[KEY], with_source=True)
    commits: list[int] = []

    def _after_commit(session):
        commits.append(1)

    event.listen(db, "after_commit", _after_commit)
    try:
        service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), "REQ-C")
    finally:
        event.remove(db, "after_commit", _after_commit)
    assert commits == [1]


def test_committed_change_survives_session_close(db):
    """接口会话在响应结束即关闭；未提交的换教室会静默丢失，教师却收到成功。"""
    add_relation(db)
    task = make_task(db, key="PA", snapshot=[KEY], with_source=True)
    task_id = task.id
    engine = db.get_bind()
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), "REQ-D")
    db.close()
    with Session(engine, expire_on_commit=False) as fresh:
        row = fresh.scalar(select(OccurrenceLocationOverride))
        assert row is not None and row.location == "B202" and row.revision == 1
        assert fresh.scalars(select(OccurrenceLocationChange)).all() != []
        assert fresh.get(InspectionTask, task_id).classroom_snapshot == "B202"


def test_rejected_change_persists_no_partial_override_row(db):
    from app.core.exceptions import ConflictError

    add_relation(db)
    task = make_task(db, key="PA", snapshot=[KEY], with_source=True)
    task_id = task.id
    engine = db.get_bind()
    with pytest.raises(ConflictError):
        # 从未覆盖过的课次（真实 revision=0）按 5 提交，必须先拒绝再写入占位行。
        service(db).change_location(
            staff_ref(db), 1, KEY, occurrence_request(revision=5), None
        )
    db.close()
    with Session(engine, expire_on_commit=False) as fresh:
        assert fresh.scalars(select(OccurrenceLocationOverride)).all() == []
        assert fresh.scalars(select(OccurrenceLocationChange)).all() == []
        assert fresh.get(InspectionTask, task_id).classroom_snapshot == "A101"


def test_other_semester_task_is_not_rewritten_by_this_room_change(db):
    """地点变更只联动本学期该课次的任务；跨学期引用同键的历史任务不能被改写。"""
    from app.modules.academic.models import Semester

    add_relation(db)
    db.add(
        Semester(
            id=2,
            code="S",
            name="补",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
            first_monday=date(2026, 8, 31),
            total_weeks=22,
        )
    )
    db.commit()
    foreign = make_task(
        db, key="PB", snapshot=[KEY], with_source=True, semester_id=2
    )
    summary = service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    assert foreign.id not in [int(t) for t in summary.affected_task_ids]
    assert foreign.classroom_snapshot == "A101"


# --------------------------------------------------------------------------- #
# 本人正式课次日历（审查 F4：日常换教室不能以“先被抽到查课”为前提）
# --------------------------------------------------------------------------- #
WEEK6 = (date(2026, 10, 5), date(2026, 10, 11))


def calendar(db, date_from, date_to, **kwargs):
    return service(db).occurrence_calendar(
        staff_ref(db), date_from=date_from, date_to=date_to, **kwargs
    )


def add_makeup(db, day):
    db.add(
        CalendarOverride(
            semester_id=1, date=day, override_type="MAKEUP",
            source_teaching_week=6, source_teaching_weekday=3,
        )
    )
    db.commit()


def test_calendar_lists_classes_that_were_never_inspected(db):
    add_relation(db)
    page = calendar(db, *WEEK6)
    assert (page.total, page.page, page.page_size) == (1, 1, 50)
    item = page.items[0]
    assert item.occurrence_key == KEY and item.task_ids == []
    assert item.base_location == "A101" and item.current_location == "A101"
    assert item.overridden is False and item.revision == 0
    assert item.course_names == ["数学"] and item.class_names == ["数学一班"]
    assert item.teaching_class_id == "1" and item.inspection_date == "2026-10-07"
    # 从未生成任务的正式课也能换教室，改完列表反映新安排
    service(db).change_location(staff_ref(db), 1, KEY, occurrence_request(), None)
    after = calendar(db, *WEEK6).items[0]
    assert after.current_location == "B202" and after.overridden and after.revision == 1


def test_calendar_links_existing_tasks_without_requiring_them(db):
    add_relation(db)
    task = make_task(db, key="PA", snapshot=[KEY], with_source=True)
    canceled = make_task(db, key="CA", snapshot=[KEY], with_source=True, canceled=True)
    item = calendar(db, *WEEK6).items[0]
    assert item.task_ids == [str(task.id)]
    assert str(canceled.id) not in item.task_ids


def test_calendar_follows_makeup_and_stop_days(db):
    add_relation(db)
    add_makeup(db, date(2026, 10, 10))
    page = calendar(db, *WEEK6)
    assert {i.occurrence_key for i in page.items} == {KEY, "s:1|2026-10-10"}
    db.add(CalendarOverride(semester_id=1, date=COURSE_DAY, override_type="STOP"))
    db.commit()
    page = calendar(db, *WEEK6)
    assert [i.occurrence_key for i in page.items] == ["s:1|2026-10-10"]
    assert page.total == 1
    changed = service(db).change_location(
        staff_ref(db), 1, "s:1|2026-10-10", occurrence_request(), None
    )
    assert changed.current_location == "B202" and changed.revision == 1


def test_calendar_merges_shared_occurrence_across_college_views(db):
    add_relation(db, local_class=1)
    add_relation(db, local_class=2)
    page = calendar(db, *WEEK6)
    assert page.total == 1
    item = page.items[0]
    assert item.occurrence_key == KEY
    assert sorted(item.class_names) == ["数学一班", "数学二班"]
    assert item.teaching_class_id == "1" and item.base_location == "A101"


def test_calendar_only_lists_days_the_appointment_covers(db):
    """任命区间外的课次不能因为“现在仍在任”就列出来让人改。"""
    db.add(
        TeachingStaffAssignment(
            staff_id=1, semester_id=1, anchor_type="LOCAL",
            teaching_class_id=1, effective_from=date(2026, 10, 8),
        )
    )
    db.commit()
    add_makeup(db, date(2026, 10, 10))
    assert [i.occurrence_key for i in calendar(db, *WEEK6).items] == ["s:1|2026-10-10"]


def test_calendar_hides_classes_without_my_relation(db):
    add_relation(db, local_class=1)
    page = calendar(db, *WEEK6, teaching_class_id=2)
    assert page.items == [] and page.total == 0


def test_calendar_rejects_invalid_ranges(db):
    from app.core.exceptions import AppError, ErrorCode

    add_relation(db)
    with pytest.raises(AppError) as inverted:
        calendar(db, date(2026, 10, 7), date(2026, 10, 6))
    assert inverted.value.http_status == 422
    assert inverted.value.code == ErrorCode.VALIDATION_ERROR
    with pytest.raises(AppError) as too_long:
        calendar(db, date(2026, 9, 1), date(2026, 11, 1))
    assert too_long.value.http_status == 422


def test_calendar_route_lists_and_validates(db):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    add_relation(db)
    ref = staff_ref(db)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: ref.user
    params = {"date_from": "2026-10-05", "date_to": "2026-10-11"}
    with TestClient(app) as client:
        ok = client.get("/api/v1/me/teaching-occurrences", params=params)
        assert ok.status_code == 200, ok.text
        payload = ok.json()["data"]
        assert payload["total"] == 1
        assert payload["items"][0]["occurrence_key"] == KEY
        assert payload["items"][0]["revision"] == 0
        assert payload["items"][0]["task_ids"] == []
        assert client.get(
            "/api/v1/me/teaching-occurrences",
            params={"date_from": "2026-10-07", "date_to": "2026-10-06"},
        ).status_code == 422
        assert client.get(
            "/api/v1/me/teaching-occurrences", params={**params, "page_size": 0}
        ).status_code == 422
