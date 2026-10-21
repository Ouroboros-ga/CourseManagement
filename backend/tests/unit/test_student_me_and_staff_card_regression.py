"""学生身份摘要与教工卡片范围/时区的真实反馈回归。"""

from datetime import date, datetime
from io import BytesIO

import openpyxl
import pytest
from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.academic.models import CourseSchedule, Student
from app.modules.academic.staff_models import TeachingStaffAssignment
from app.modules.identity.models import UserAccount
from app.modules.identity.schemas import CurrentUserResponse
from app.modules.identity.staff_deps import resolve_app_context
from app.modules.inspection.models import InspectionTask, TaskScheduleSource
from app.modules.inspection.staff_record_query import StaffRecordQueryService

from tests.unit.test_staff_records import _teacher_actor, staff_records_db


@pytest.fixture
def records_db():
    yield from staff_records_db.__wrapped__()


def test_other_tasks_cannot_borrow_a_teachers_source_mapping(records_db, monkeypatch):
    from app.modules.inspection import staff_record_query

    monkeypatch.setattr(staff_record_query, "business_today", lambda: date(2026, 10, 21))
    db = records_db
    db.add(TeachingStaffAssignment(staff_id=101, semester_id=1, anchor_type="LOCAL",
        teaching_class_id=1, effective_from=date(2026, 9, 1)))
    schedule = CourseSchedule(semester_id=1, teaching_class_id=1, weekday=1,
                              start_period=1, end_period=2)
    db.add(schedule)
    db.flush()
    # 为本人课程建立来源行后，原嵌套 EXISTS 会把该来源误用于其他任务。
    db.add(TaskScheduleSource(task_id=1, course_schedule_id=schedule.id, teaching_class_id=1))
    db.commit()
    query = StaffRecordQueryService(db, _teacher_actor())
    cards, total = query.list_cards("teaching", PageParams(1, 50),
                                    inspection_date=date(2026, 10, 19))
    assert total == 1 and [row.task_id for row in cards] == ["1"]
    assert cards[0].counts.total == 3
    with pytest.raises(NotFoundError):
        query.get_card(2, "teaching")
    with pytest.raises(NotFoundError):
        query.list_attendance(2, "teaching", None, PageParams(1, 50))
    summary = query.get_summary("teaching")
    assert summary.student_counts.total == 3
    data, _ = query.export_excel("teaching")
    workbook = openpyxl.load_workbook(BytesIO(data), read_only=True)
    values = [value for row in workbook.active.iter_rows(values_only=True) for value in row]
    workbook.close()
    assert "S004" not in values


def test_card_includes_an_unambiguous_utc_offset(records_db):
    db = records_db
    task = db.get(InspectionTask, 1)
    task.activity_start_at = datetime(2026, 10, 21, 10, 50)
    task.activity_end_at = datetime(2026, 10, 21, 12, 25)
    query = StaffRecordQueryService(db, _teacher_actor())
    card = query._build_card(task, "teaching", {}, ("RECORDED", None))
    assert card.starts_at == "2026-10-21T10:50:00+00:00"
    assert card.ends_at == "2026-10-21T12:25:00+00:00"


def test_student_me_summary_has_school_identity_without_new_permissions(records_db):
    db = records_db
    db.get(UserAccount, 10).student_id = 1
    db.get(Student, 1).student_no = "00123456"
    db.commit()
    actor = _teacher_actor()
    context = resolve_app_context(db, actor)
    assert context["student"]["student_no"] == "00123456"
    assert context["student"]["college_name"] == "学院一"
    assert context["student"]["administrative_class_name"] == "计算机1班"
    result = CurrentUserResponse.build(id=10, username=actor.username,
        display_name=actor.display_name, status=actor.status, roles=actor.roles,
        permissions=actor.permissions, app_context=context).model_dump()
    assert result["student_no"] == "00123456" and result["college_name"] == "学院一"
    assert result["permissions"] == actor.permissions
    assert context["staff"]["staff_no"] == "T001"


def test_no_bound_student_never_infers_student_identity_from_name_or_roles(records_db):
    db = records_db
    context = resolve_app_context(db, _teacher_actor())
    assert context["student"] is None


def test_student_summary_follows_dated_enrollment_and_unbinding(records_db, monkeypatch):
    from app.modules.academic.enrollment_models import StudentEnrollment
    from app.modules.identity import student_summary

    monkeypatch.setattr(student_summary, "business_today", lambda: date(2026, 10, 21))
    db = records_db
    account = db.get(UserAccount, 10)
    account.student_id = 1
    # 当前档案已是新班，生效时间线必须优先，不能把未来变更提前显示。
    db.get(Student, 1).administrative_class_id = 3
    first = StudentEnrollment(student_id=1, administrative_class_id=1, college_id=1,
        effective_from=date(2026, 9, 1), effective_to=date(2026, 10, 22),
        status="ENROLLED", revision=0, snapshot={})
    future = StudentEnrollment(student_id=1, administrative_class_id=3, college_id=2,
        effective_from=date(2026, 10, 22), status="ENROLLED", revision=1, snapshot={})
    db.add_all([first, future])
    db.commit()
    assert resolve_app_context(db, _teacher_actor())["student"]["college_name"] == "学院一"
    first.effective_to = date(2026, 10, 20)
    db.commit()
    assert resolve_app_context(db, _teacher_actor())["student"]["college_name"] is None
    account.student_id = None
    db.commit()
    assert resolve_app_context(db, _teacher_actor())["student"] is None


def test_student_me_http_response_preserves_new_fields(records_db):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    db = records_db
    db.get(UserAccount, 10).student_id = 1
    db.get(Student, 1).student_no = "00123456"
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _teacher_actor
    with TestClient(app) as client:
        response = client.get('/api/v1/me')
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["student_no"] == "00123456"
    assert data["college_name"] == "学院一"
    assert data["app_context"]["student"]["student_no"] == data["student_no"]
