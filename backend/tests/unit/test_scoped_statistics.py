import pytest
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.report.schemas import AttendanceStatsQuery
from app.modules.report.service import StatisticsService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_statistics_cannot_include_other_college_or_unknown_tasks(campus, monkeypatch):
    from app.modules.inspection.models import InspectionTask
    from sqlalchemy import select

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    task = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[4]["id"]))
    )
    result = StatisticsService(db).attendance_stats(
        actor,
        AttendanceStatsQuery(semester_id=task.semester_id, week_no=task.week_no),
        include_tasks=True,
    )
    assert result.eligible_task_count == 1
    assert len(result.tasks) == 1 and int(result.tasks[0].task_id) == task.id


def test_class_duties_with_same_name_do_not_cross_college(campus, monkeypatch):
    from app.modules.academic.models import AdministrativeClass
    from app.modules.report.repository import ReportRepository
    from sqlalchemy import select

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    own = db.scalar(
        select(AdministrativeClass).where(AdministrativeClass.college_id == int(campus[4]["id"]))
    )
    other = db.scalar(
        select(AdministrativeClass).where(AdministrativeClass.college_id == int(campus[5]["id"]))
    )
    other.class_name = own.class_name
    other.head_teacher = "Other college private teacher"
    db.commit()
    duties = ReportRepository(db, college_ids=frozenset({int(campus[4]["id"])})).class_duties_map(
        {own.class_name}
    )
    assert duties[own.class_name][2] == own.id
    assert duties[own.class_name][0] != other.head_teacher


def test_existing_statistics_service_refreshes_primary_binding(campus, monkeypatch):
    from app.modules.inspection.models import InspectionTask
    from sqlalchemy import select

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    own = db.scalar(select(InspectionTask).where(InspectionTask.college_id == int(campus[4]["id"])))
    foreign = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[5]["id"]))
    )
    service = StatisticsService(db)
    query = AttendanceStatsQuery(
        semester_id=own.semester_id, date_from=own.inspection_date, date_to=own.inspection_date
    )
    assert (
        int(service.attendance_stats(actor, query, include_tasks=True).tasks[0].task_id) == own.id
    )
    db.get(TeacherCollegeBinding, actor.id).college_id = int(campus[5]["id"])
    db.commit()
    assert (
        int(service.attendance_stats(actor, query, include_tasks=True).tasks[0].task_id)
        == foreign.id
    )
