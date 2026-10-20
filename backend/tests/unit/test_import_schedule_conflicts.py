"""确认集合按实际周次核对课表，来源行号不构成新的授课安排。"""

import pytest
from app.core.config import get_settings
from app.modules.academic.models import AdministrativeClass, CourseSchedule, CourseScheduleWeek
from app.modules.importer.confirmation_set import ImportConfirmationSet
from sqlalchemy import select

from tests.unit.test_scoped_grid_mapping import school_periods
from tests.unit.test_staff_importer import configured, setup_env, sheet  # noqa: F401


@pytest.fixture
def schedule_env(campus, monkeypatch):
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", False)
    service, db, actor, cid, _, sid = setup_env(campus)
    school_periods(db, sid)
    db.add(AdministrativeClass(college_id=cid, class_code="CONFIRM_A", class_name="核对2601"))
    db.commit()
    return service, db, actor, sid


def grid_preview(env, blocks):
    service, _, actor, sid = env
    return service.create_preview(
        actor,
        target="grid_timetable",
        semester_id=sid,
        teaching_class_id=None,
        filename="核对2601课表.xlsx",
        replace=False,
        request_id=None,
        content=sheet(
            [
                ["核对2601课表"],
                ["节次", "星期一"],
                *[[str(index), block] for index, block in enumerate(blocks, 1)],
            ]
        ),
    )


def cell(weeks, room="A101", period="3-4", name="机械设计"):
    return f"{name}\r\n◇{weeks}周({period}节)◇{room}◇测试教师◇选课人数：32"


@pytest.mark.parametrize(
    "first,second,total",
    [
        ("1-10", "11-14", 14),
        ("1-17(单)", "2-16(双)", 17),
        ("13-14", "15-16", 4),
    ],
)
def test_one_grid_file_allows_disjoint_weeks_and_persists_both(schedule_env, first, second, total):
    service, db, _, _ = schedule_env
    preview = grid_preview(schedule_env, [cell(first) + "\r\n" + cell(second, "A102")])
    assert preview.can_confirm, preview.errors
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    assert plan["can_confirm"], plan["files"][0]["issues"]
    changes = [r for r in plan["files"][0]["changes"] if r["entity"] == "schedule"]
    assert len({r["key"] for r in changes}) == 2
    assert all(r["action"] == "CREATE" for r in changes)
    wizard.confirm([int(preview.id)], plan["revision"], None)
    schedules = db.scalars(
        select(CourseSchedule).where(CourseSchedule.classroom.in_(["A101", "A102"]))
    ).all()
    assert len(schedules) == 2
    weeks = [
        set(
            db.scalars(
                select(CourseScheduleWeek.week_no).where(CourseScheduleWeek.schedule_id == row.id)
            )
        )
        for row in schedules
    ]
    assert not weeks[0] & weeks[1]
    assert len(weeks[0] | weeks[1]) == total


def test_identical_schedule_from_different_source_rows_is_saved_once(schedule_env):
    service, db, _, _ = schedule_env
    preview = grid_preview(schedule_env, [cell("1-10"), cell("1-10")])
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    assert plan["can_confirm"], plan["files"][0]["issues"]
    assert any(
        r.get("code") == "DUPLICATE_SCHEDULE_ROW" and r["severity"] == "warning"
        for r in plan["files"][0]["issues"]
    )
    wizard.confirm([int(preview.id)], plan["revision"], None)
    assert (
        len(db.scalars(select(CourseSchedule).where(CourseSchedule.classroom == "A101")).all()) == 1
    )


def test_overlapping_weeks_with_different_rooms_remain_blocked_with_specific_source(schedule_env):
    service, db, _, _ = schedule_env
    preview = grid_preview(schedule_env, [cell("1-10") + "\r\n" + cell("10-14", "A102")])
    plan = ImportConfirmationSet(service).preview([int(preview.id)])
    assert not plan["can_confirm"]
    errors = [r for r in plan["files"][0]["issues"] if r["severity"] == "error"]
    assert any(
        "机械设计" in r["message"] and "10" in r["message"] and r.get("row") == 3 for r in errors
    )
    assert not any("多个文件修改同一条资料" in r["message"] for r in errors)
    assert not db.scalars(select(CourseSchedule).where(CourseSchedule.classroom == "A102")).all()


def test_two_files_same_course_different_weeks_can_be_confirmed_together(schedule_env):
    service, db, actor, sid = schedule_env
    header = [
        "教学班码",
        "课程代码",
        "课程名称",
        "星期",
        "开始大节",
        "结束大节",
        "周次",
        "上课地点",
    ]
    previews = [
        service.create_preview(
            actor,
            target="timetable",
            semester_id=sid,
            teaching_class_id=None,
            filename=f"part-{index}.xlsx",
            replace=False,
            request_id=None,
            content=sheet([header, ["SPLIT", "SPLIT_C", "分段课程", "1", "1", "1", weeks, room]]),
        )
        for index, (weeks, room) in enumerate([("1-10", "A101"), ("11-14", "A102")])
    ]
    wizard = ImportConfirmationSet(service)
    ids = [int(p.id) for p in previews]
    plan = wizard.preview(ids)
    assert plan["can_confirm"], [f["issues"] for f in plan["files"]]
    wizard.confirm(ids, plan["revision"], None)
    assert (
        len(
            db.scalars(
                select(CourseSchedule).where(CourseSchedule.classroom.in_(["A101", "A102"]))
            ).all()
        )
        == 2
    )


@pytest.mark.parametrize("difference", ["teacher", "room"])
def test_same_window_different_business_values_is_not_deduplicated(schedule_env, difference):
    service, _, _, _ = schedule_env
    second = (
        cell("1-10", "A102")
        if difference == "room"
        else cell("1-10").replace("测试教师", "另一教师")
    )
    preview = grid_preview(schedule_env, [cell("1-10"), second])
    plan = ImportConfirmationSet(service).preview([int(preview.id)])
    assert not plan["can_confirm"]
    assert any(r.get("code") == "SCHEDULE_OVERLAP" for r in plan["files"][0]["issues"])
