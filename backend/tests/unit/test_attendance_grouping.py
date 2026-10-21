"""完整授权集合分组；不以本页记录或当前学籍代替历史事实。"""

import pytest
from app.common.pagination import PageParams
from app.modules.attendance.models import AttendanceRecord
from app.modules.inspection.models import InspectionTask, TaskRosterMember

from tests.unit.test_scoped_attendance import attendance_fixture, prepare, service


@pytest.fixture
def campus():
    yield from attendance_fixture.__wrapped__()


def test_grouped_tasks_keep_distinct_occurrences_and_scope(campus):
    from app.modules.attendance.browse import AttendanceFilters

    db, actor, a, _, own, foreign = prepare(campus)
    original = db.get(InspectionTask, own.task_id)
    second = InspectionTask(
        task_key="SECOND", semester_id=original.semester_id,
        inspection_date=original.inspection_date, week_no=2,
        inspection_type="COURSE", start_period=3, end_period=4,
        college_id=int(a["id"]), course_name_snapshot="同名课程",
    )
    original.course_name_snapshot = "同名课程"
    db.add(second)
    db.flush()
    db.add(AttendanceRecord(task_id=second.id, student_id=own.student_id,
                            effective_type="NORMAL", current_version=1))
    db.commit()
    result = service(db, actor, a["id"]).list_groups(
        actor, PageParams(1, 1), group_by="task", semester_id=None,
        effective_type=None, filters=AttendanceFilters(),
    )
    assert result["total"] == 2
    assert len(result["items"]) == 1
    assert result["summary"]["record_count"] == 2
    assert result["summary"]["late_count"] == 1
    assert result["summary"]["absent_count"] == 0  # 另一学院不能进入计数。
    assert result["items"][0]["task_id"] != str(foreign.task_id)


def test_class_group_and_drilldown_use_snapshot_not_current_class(campus):
    from app.modules.academic.models import Student
    from app.modules.attendance.browse import AttendanceFilters

    db, actor, a, _, own, _ = prepare(campus)
    task = db.get(InspectionTask, own.task_id)
    student = db.get(Student, own.student_id)
    historical_class = student.administrative_class_id
    db.add(TaskRosterMember(task_id=task.id, roster_version=task.roster_version,
        student_id=student.id, student_no="00123456", name="历史姓名",
        administrative_class_id_snapshot=historical_class, class_name_snapshot="原行政班"))
    # 额外旧名单版本不允许把同一条考勤重复计数。
    db.add(TaskRosterMember(task_id=task.id, roster_version=task.roster_version + 1,
        student_id=student.id, student_no="00123456", name="后来姓名",
        class_name_snapshot="后来班级"))
    student.administrative_class_id = None
    db.commit()
    scoped = service(db, actor, a["id"])
    filters = AttendanceFilters(administrative_class_id=historical_class)
    result = scoped.list_groups(actor, PageParams(1, 50), group_by="administrative_class",
        semester_id=None, effective_type=None, filters=filters)
    assert result["items"][0]["class_name"] == "原行政班"
    assert result["items"][0]["record_count"] == 1
    page = scoped.list_attendance(actor, PageParams(1, 50), task_id=task.id,
        semester_id=None, effective_type=None, filters=filters)
    assert page["total"] == 1
    assert page["items"][0]["administrative_class_name"] == "原行政班"
    assert page["items"][0]["student_no"] == "00123456"
    assert scoped.list_groups(actor, PageParams(1, 50), group_by="task",
        semester_id=None, effective_type=None,
        filters=AttendanceFilters(keyword="不存在"))["total"] == 0


def test_unknown_snapshot_is_explicit_and_status_filters_precede_grouping(campus):
    from app.modules.attendance.browse import AttendanceFilters

    db, actor, a, _, own, _ = prepare(campus)
    scoped = service(db, actor, a["id"])
    result = scoped.list_groups(actor, PageParams(1, 50), group_by="administrative_class",
        semester_id=None, effective_type="LATE", filters=AttendanceFilters(unknown_class=True))
    assert result["items"][0]["administrative_class_id"] is None
    assert result["items"][0]["class_name"] == "历史班级待核对"
    assert result["summary"]["record_count"] == 1
    assert scoped.list_groups(actor, PageParams(1, 50), group_by="task",
        semester_id=None, effective_type="NORMAL", filters=AttendanceFilters())["total"] == 0


def test_approved_roster_and_filters_are_shared_by_summary_and_detail(campus):
    from datetime import timedelta

    from app.core.database import utcnow
    from app.modules.attendance.browse import AttendanceFilters
    from app.modules.inspection.models import InspectionSubmission

    db, actor, a, _, own, _ = prepare(campus)
    task = db.get(InspectionTask, own.task_id)
    task.roster_version = 2
    for version, name in [(1, "正式班"), (2, "后改班")]:
        db.add(TaskRosterMember(task_id=task.id, roster_version=version,
            student_id=own.student_id, student_no="00001", name=name,
            class_name_snapshot=name))
    db.add(InspectionSubmission(task_id=task.id, attempt_no=1, volunteer_user_id=actor.id,
        roster_version=1, result="NORMAL", review_status="APPROVED", submitted_at=utcnow()))
    db.commit()
    scoped = service(db, actor, a["id"])
    filters = AttendanceFilters(keyword="正式班", start_date=task.inspection_date,
                                end_date=task.inspection_date, abnormal_only=True)
    grouped = scoped.list_groups(actor, PageParams(1, 50), group_by="task",
        semester_id=None, effective_type=None, filters=filters)
    assert grouped["summary"]["record_count"] == 1
    assert grouped["items"][0]["volunteer_name"]
    detail = scoped.list_attendance(actor, PageParams(1, 50), task_id=task.id,
        semester_id=None, effective_type=None, filters=filters)
    assert detail["items"][0]["administrative_class_name"] == "正式班"
    assert detail["items"][0]["name"] == "正式班"
    assert scoped.list_groups(actor, PageParams(1, 50), group_by="task",
        semester_id=None, effective_type=None, filters=AttendanceFilters(
            start_date=task.inspection_date + timedelta(days=1)))["total"] == 0
    own.effective_type = "NORMAL"
    db.commit()
    assert scoped.list_groups(actor, PageParams(1, 50), group_by="task",
        semester_id=None, effective_type=None, filters=filters)["summary"]["record_count"] == 0


def test_group_http_contract_and_invalid_date_range(campus, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    db, actor, a, _, own, _ = prepare(campus)
    monkeypatch.setattr(get_settings(), "campus_configuration_enabled", True)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        path = f"/api/v1/colleges/{a['id']}/attendance/groups"
        response = client.get(path, params={"group_by": "task", "page_size": 50})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["items"][0]["task_id"] == str(own.task_id)
        assert data["summary"]["record_count"] == 1
        assert client.get(path, params={"group_by": "not-a-view"}).status_code == 422
        assert client.get(path, params={"start_date": "2026-10-23",
                                      "end_date": "2026-10-19"}).status_code == 422
        # scoped 模式继续关闭旧全校管理入口。
        assert client.get("/api/v1/attendance/groups").status_code == 403
