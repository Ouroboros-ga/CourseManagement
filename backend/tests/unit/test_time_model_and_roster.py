"""Tests for unified UTC ISO 8601 timestamp serialization and timetable roster cliff elimination."""

from datetime import UTC, date, datetime, timedelta, timezone

import app.core.database  # noqa: F401 - ensures global datetime serialization registered
import pytest
from app.core.database import iso_utc
from app.modules.academic.enrollment_models import StudentEnrollment, TeachingClassAudience
from app.modules.academic.models import CourseScheduleWeek, Student
from app.modules.academic.roster_index import RosterIndex
from app.modules.academic.scoped_service import ScopedAcademicService
from app.modules.academic.scoped_timetable import master_timetable
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_campus_ownership import legacy


@pytest.fixture(name="campus")
def scoped_fixture():
    yield from campus_fixture.__wrapped__()


def test_iso_utc_formatting():
    assert iso_utc(None) is None

    # Naive datetime (interpreted as UTC)
    dt_naive = datetime(2026, 10, 16, 16, 0, 0)
    assert iso_utc(dt_naive) == "2026-10-16T16:00:00Z"

    # Aware UTC datetime
    dt_utc = datetime(2026, 10, 16, 16, 0, 0, tzinfo=UTC)
    assert iso_utc(dt_utc) == "2026-10-16T16:00:00Z"

    # Aware non-UTC datetime (+08:00)
    cst = timezone(timedelta(hours=8))
    dt_cst = datetime(2026, 10, 17, 0, 0, 0, tzinfo=cst)
    assert iso_utc(dt_cst) == "2026-10-16T16:00:00Z"


def test_pydantic_and_fastapi_jsonable_encoder_datetime_serialization():
    class Item(BaseModel):
        created_at: datetime
        deadline_at: datetime | None = None

    now_naive = datetime(2026, 10, 16, 16, 30, 0)
    item = Item(created_at=now_naive, deadline_at=now_naive)

    # Pydantic dump
    dumped = item.model_dump(mode="json")
    assert dumped["created_at"] == "2026-10-16T16:30:00Z"
    assert dumped["deadline_at"] == "2026-10-16T16:30:00Z"

    # FastAPI jsonable_encoder
    encoded_dict = jsonable_encoder({"time": now_naive})
    assert encoded_dict["time"] == "2026-10-16T16:30:00Z"

    encoded_model = jsonable_encoder(item)
    assert encoded_model["created_at"] == "2026-10-16T16:30:00Z"


def test_master_timetable_roster_fallback_before_baseline_date(campus):
    config, db, admin, teacher, a, b = campus
    one, teaching, schedule, task = legacy(db)
    one.college_id = int(a["id"])
    teaching.college_id = int(a["id"])
    schedule.college_id = int(a["id"])
    schedule.weekday = 1
    db.add(CourseScheduleWeek(schedule_id=schedule.id, week_no=5))
    db.flush()

    student = Student(student_no="S001", name="测试学生", administrative_class_id=one.id)
    db.add(student)
    db.flush()

    # 关联教学班受众行政班
    db.add(TeachingClassAudience(teaching_class_id=teaching.id, administrative_class_id=one.id))
    db.flush()

    # 模拟 2026-10-14 迁移基线：effective_from 为 2026-10-14
    # 在查询 2026-10-12 (周一) 时存在日期断崖
    baseline = StudentEnrollment(
        student_id=student.id,
        revision=0,
        status="ENROLLED",
        administrative_class_id=one.id,
        college_id=int(a["id"]),
        effective_from=date(2026, 10, 14),
        effective_to=None,
        superseded=False,
        historical_confirmed=False,
        snapshot={"origin": "MIGRATION_CURRENT_ONLY"},
    )
    db.add(baseline)
    db.commit()

    # 未加入 fallback 前，2026-10-12 查出为 0 人；有 fallback 时，回退获取投影名单
    index = RosterIndex(db, [teaching.id])
    day_before_baseline = date(2026, 10, 12)
    assert len(index.at(day_before_baseline).get(teaching.id, [])) == 0
    assert len(index.for_personal_timetable(day_before_baseline).get(teaching.id, [])) == 1

    # 在 master_timetable 接口中，通过 fallback 成功消除断崖
    grant(config, admin, teacher, a, ["academic.read"])
    scoped = ScopedAcademicService(db, teacher, int(a["id"]))
    result = master_timetable(scoped, schedule.semester_id, week_no=5, weekday=1)
    assert result["total"] == 1
    assert result["items"][0]["enrolled_student_count"] == 1
    assert result["items"][0]["is_inspectable"] is True


def test_scoped_teaching_class_roster_audience_fallback(campus):
    config, db, admin, teacher, a, b = campus
    one, teaching, schedule, task = legacy(db)
    one.college_id = int(a["id"])
    teaching.college_id = int(a["id"])

    student = Student(student_no="S002", name="张三", administrative_class_id=one.id)
    db.add(student)
    db.flush()

    # 教学班未写入 TeachingClassStudent，仅有关联 TeachingClassAudience
    db.add(TeachingClassAudience(teaching_class_id=teaching.id, administrative_class_id=one.id))
    db.commit()

    grant(config, admin, teacher, a, ["academic.read", "student.read"])
    scoped = ScopedAcademicService(db, teacher, int(a["id"]))
    roster = scoped.list_roster(teaching.id)
    assert len(roster) == 1
    assert roster[0]["student_no"] == "S002"
    assert roster[0]["name"] == "张三"
    assert roster[0]["administrative_class_name"] == one.class_name
