"""分页之前筛选，计数与摘要不能取当前页，也不能越过学院边界。"""

import pytest
from app.common.pagination import PageParams
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.repository import InspectionRepository
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_attendance import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_linked_teaching_class_task_assembly_uses_sql_distinct(campus):
    from app.modules.academic.models import AdministrativeClass, Student, TeachingClass, TeachingClassStudent
    from app.modules.inspection.service import InspectionService
    from sqlalchemy import event

    db, _, a, _, own, _ = prepare(campus)
    task = db.get(InspectionTask, own.task_id)
    teaching = db.scalar(select(TeachingClass).where(TeachingClass.college_id == int(a["id"])))
    task.teaching_class_id = teaching.id
    db.add(TeachingClassStudent(teaching_class_id=teaching.id, student_id=own.student_id))
    db.commit()
    statements = []

    def collect(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        rows = InspectionService(db)._assemble_tasks([task])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)
    expected = db.get(
        AdministrativeClass, db.get(Student, own.student_id).administrative_class_id
    ).class_name
    assert len(rows) == 1 and rows[0].administrative_classes == [expected]
    projections = [s for s in statements if "teaching_class_student" in s and "JOIN student" in s]
    assert len(projections) == 1 and "SELECT DISTINCT" in projections[0]


def test_task_search_count_summary_and_second_page(campus):
    db, _, a, _, own, _ = prepare(campus)
    source = db.get(InspectionTask, own.task_id)
    db.add_all(
        [
            InspectionTask(
                task_key=f"PAGE-{i}",
                semester_id=source.semester_id,
                inspection_date=source.inspection_date,
                week_no=source.week_no,
                inspection_type="COURSE",
                start_period=1,
                end_period=2,
                college_id=int(a["id"]),
                course_name_snapshot=f"分页课程{i}",
            )
            for i in range(105)
        ]
    )
    db.commit()
    repo = InspectionRepository(db)
    scope = select(InspectionTask).where(InspectionTask.college_id == int(a["id"]))
    first, total = repo.list_tasks(PageParams(1, 50), scope_filter=scope, keyword="分页课程")
    second, second_total = repo.list_tasks(
        PageParams(2, 50), scope_filter=scope, keyword="分页课程"
    )
    assert len(first) == len(second) == 50
    assert total == second_total == 105
    assert not ({r.id for r in first} & {r.id for r in second})
    found, count = repo.list_tasks(PageParams(1, 50), scope_filter=scope, keyword="分页课程104")
    assert count == 1 and found[0].course_name_snapshot == "分页课程104"
    summary = repo.task_summary(scope_filter=scope, keyword="分页课程")
    assert summary["total"] == 105 and summary["unassigned"] == 105
    assert sum(summary["dates"].values()) == 105
    from sqlalchemy import event

    statements = []

    def collect(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        repo.list_tasks(PageParams(1, 50), scope_filter=scope)
        repo.task_summary(scope_filter=scope)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)
    assert len(statements) == 3  # COUNT + one page + grouped summary; no roster-history eager load
    assert "LIMIT" in statements[1]


def test_task_literal_search_and_status(campus):
    db, _, a, _, own, _ = prepare(campus)
    source = db.get(InspectionTask, own.task_id)
    source.course_name_snapshot = "100%完成_示例"
    db.commit()
    repo = InspectionRepository(db)
    scope = select(InspectionTask).where(InspectionTask.college_id == int(a["id"]))
    rows, total = repo.list_tasks(PageParams(1, 50), scope_filter=scope, keyword="%完成_")
    assert total == 1 and rows[0].id == own.task_id
    rows, total = repo.list_tasks(PageParams(1, 50), scope_filter=scope, status="CANCELLED")
    assert total == 0 and rows == []


def test_submission_filters_run_before_pagination(campus):
    from app.core.database import utcnow
    from app.modules.inspection.models import InspectionSubmission

    db, teacher, a, _, own, foreign = prepare(campus)
    repo = InspectionRepository(db, college_ids=frozenset({int(a["id"])}))
    db.add_all(
        [
            InspectionSubmission(
                task_id=own.task_id,
                attempt_no=i + 1,
                volunteer_user_id=teacher.id,
                roster_version=1,
                submitted_at=utcnow(),
                result="ABNORMAL" if i == 110 else "NORMAL",
                review_status="PENDING",
            )
            for i in range(111)
        ]
    )
    db.add(
        InspectionSubmission(
            task_id=foreign.task_id,
            attempt_no=1,
            volunteer_user_id=teacher.id,
            roster_version=1,
            submitted_at=utcnow(),
            result="ABNORMAL",
            review_status="PENDING",
        )
    )
    db.commit()
    rows, total = repo.list_management_submissions(PageParams(2, 50), review_status="PENDING")
    assert len(rows) == 50 and total == 111
    rows, total = repo.list_management_submissions(PageParams(1, 50), result="ABNORMAL")
    assert total == 1 and rows[0].task_id == own.task_id
    assert repo.management_submission_summary() == {
        "pending": 111,
        "normal": 110,
        "abnormal": 1,
        "reviewed": 0,
    }


def test_export_uses_same_search_and_scope_without_detail_assembly(campus, monkeypatch):
    from app.modules.inspection.service import InspectionService

    db, teacher, a, _, own, _ = prepare(campus)
    source = db.get(InspectionTask, own.task_id)
    source.course_name_snapshot = "EXPORT_LITERAL%"
    db.commit()
    service = InspectionService(db)
    monkeypatch.setattr(service, "_require", lambda *_: None)
    monkeypatch.setattr(
        service,
        "_scope_filter",
        lambda *_: select(InspectionTask).where(InspectionTask.college_id == int(a["id"])),
    )
    monkeypatch.setattr(service, "_assemble_tasks", lambda *_: pytest.fail("导出不能装配名单详情"))
    result = service.export_tasks(teacher, keyword="LITERAL%")
    assert result["total"] == 1 and result["items"][0]["id"] == str(own.task_id)
    assert service.export_tasks(teacher, pending_change=True)["total"] == 0


def test_legacy_qualification_read_does_not_repair_roles(campus, monkeypatch):
    from app.modules.academic.models import VolunteerQualification
    from app.modules.academic.service import AcademicService

    db, teacher, a, _, own, _ = prepare(campus)
    student_id = own.student_id
    task = db.get(InspectionTask, own.task_id)
    db.add(
        VolunteerQualification(
            semester_id=task.semester_id,
            student_id=student_id,
            college_id=int(a["id"]),
            enabled=True,
            created_by=teacher.id,
        )
    )
    db.commit()
    service = AcademicService(db)
    monkeypatch.setattr(
        service, "_grant_volunteer_role", lambda *_: pytest.fail("GET 不能写入角色或账号")
    )
    page = service.list_volunteer_qualifications(
        PageParams(1, 50), semester_id=task.semester_id, enabled=True, student_ids=[student_id]
    )
    assert page["total"] == 1
