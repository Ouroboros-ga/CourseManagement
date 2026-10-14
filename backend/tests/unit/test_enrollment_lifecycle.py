"""学籍生效区间及交接回归；不使用真实学生数据。"""

from datetime import date

import pytest
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models import Base
from app.modules.academic.enrollment_models import College, TeacherCollegeBinding
from app.modules.academic.enrollment_schemas import EnrollmentChangeRequest
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.models import Role, UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.seed import sync_registry
from app.modules.organization.models import School
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def school():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sync_registry(db)
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all(
            [
                College(id=1, school_id=1, code="A", name="学院A"),
                College(id=2, school_id=1, code="B", name="学院B"),
            ]
        )
        db.flush()
        db.add_all(
            [
                AdministrativeClass(
                    id=1, class_code="A1", class_name="A1", college="学院A", college_id=1
                ),
                AdministrativeClass(
                    id=2, class_code="A2", class_name="A2", college="学院A", college_id=1
                ),
                AdministrativeClass(
                    id=3, class_code="B1", class_name="B1", college="学院B", college_id=2
                ),
            ]
        )
        db.flush()
        db.add(Student(id=1, student_no="2026001", name="样例学生", administrative_class_id=1))
        for uid, role in [(1, "SUPER_ADMIN"), (2, "TEACHER_ADMIN"), (3, "STUDENT")]:
            db.add(
                UserAccount(
                    id=uid,
                    username=f"u{uid}",
                    display_name=f"用户{uid}",
                    student_id=1 if uid == 3 else None,
                    roles=[db.scalar(select(Role).where(Role.code == role))],
                )
            )
        db.flush()
        db.add(TeacherCollegeBinding(user_id=2, college_id=1))
        db.commit()
        yield db


def change(target=2, version=0, when=date(2026, 9, 1), **kwargs):
    return EnrollmentChangeRequest(
        target_class_id=target, effective_date=when, lock_version=version, **kwargs
    )


def test_transfer_preserves_number_binding_and_history(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    result = service.commit(2, 1, change(), request_id="test")
    assert result["student_no"] == "2026001"
    assert school.get(UserAccount, 3).student_id == 1
    assert school.get(Student, 1).administrative_class_id == 2
    assert service.at(1, date(2026, 10, 1)).administrative_class_id == 2
    history = service.history(2, 1)
    assert history["changes"][0]["effective_date"] == "2026-09-01"
    with pytest.raises(ConflictError):
        service.commit(2, 1, change(version=0), request_id="stale")


def test_only_school_admin_can_cross_college(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        service.commit(2, 1, change(target=3), request_id=None)
    school.rollback()
    service.commit(1, 1, change(target=3), request_id=None)
    with pytest.raises(PermissionDeniedError):
        service.history(2, 1)


def test_future_change_does_not_move_current_projection(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    result = service.commit(2, 1, change(when=date(2026, 11, 1)), request_id=None)
    assert result["state"] == "SCHEDULED"
    assert school.get(Student, 1).administrative_class_id == 1
    assert service.at(1, date(2026, 10, 31)).administrative_class_id == 1
    assert service.at(1, date(2026, 11, 1)).administrative_class_id == 2


def test_departure_keeps_identity_and_ten_year_calendar_retention(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    result = service.commit(
        2, 1, change(target=None, kind="GRADUATE", when=date(2026, 10, 1)), request_id=None
    )
    assert result["history_until"] == "2036-10-01"
    assert school.get(UserAccount, 3).student_id == 1
    assert service.at(1, date(2026, 10, 1)).status == "GRADUATED"
    assert service.history(3, 1)["student_no"] == "2026001"


def test_backdated_change_cannot_erase_later_confirmed_change(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    service.commit(2, 1, change(when=date(2026, 10, 1)), request_id=None)
    with pytest.raises(ConflictError):
        service.commit(2, 1, change(when=date(2026, 9, 1), version=1), request_id=None)


def test_cancel_future_plan_restores_source_without_deleting_audit(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    result = service.commit(2, 1, change(when=date(2026, 11, 1)), request_id=None)
    service.cancel(2, 1, int(result["id"]), 1)
    assert service.at(1, date(2026, 11, 2)).administrative_class_id == 1
    assert service.history(2, 1)["changes"][0]["state"] == "CANCELED"


def test_due_projection_is_idempotent(school):
    EnrollmentService(school, today=date(2026, 10, 14)).commit(
        1, 1, change(target=3, when=date(2026, 11, 1)), request_id=None
    )
    due = EnrollmentService(school, today=date(2026, 11, 1))
    assert due.apply_due() == 1
    assert due.apply_due() == 0
    assert school.get(Student, 1).administrative_class_id == 3


def test_backdated_correction_preserves_later_enrollment_and_current_identity(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    service.commit(1, 1, change(target=2, when=date(2026, 10, 1)), request_id=None)
    service.commit(1, 1, change(target=1, when=date(2026, 10, 5), version=1), request_id=None)
    correction = change(target=3, when=date(2026, 10, 3), version=2).model_copy(
        update={"correct_existing": True}
    )
    service.commit(1, 1, correction, request_id=None)
    assert service.at(1, date(2026, 10, 2)).administrative_class_id == 2
    assert service.at(1, date(2026, 10, 3)).administrative_class_id == 3
    assert service.at(1, date(2026, 10, 5)).administrative_class_id == 1
    assert school.get(Student, 1).administrative_class_id == 1
    assert school.get(UserAccount, 3).student_id == 1


def test_cancel_future_change_after_correction_restores_immediate_predecessor(school):
    service = EnrollmentService(school, today=date(2026, 10, 14))
    service.commit(1, 1, change(target=2, when=date(2026, 10, 1)), request_id=None)
    future = service.commit(
        1, 1, change(target=2, when=date(2026, 11, 1), version=1), request_id=None
    )
    service.commit(
        1,
        1,
        change(target=1, when=date(2026, 10, 3), version=2).model_copy(
            update={"correct_existing": True}
        ),
        request_id=None,
    )
    service.cancel(1, 1, int(future["id"]), 3)
    assert service.at(1, date(2026, 11, 2)).administrative_class_id == 1


def test_diff_import_never_transfers_or_reactivates_implicitly(school):
    from app.modules.importer.student_data_service import StudentDataService

    service = StudentDataService(school)
    plan = service.preview(
        2,
        college_id=1,
        rows=[{"student_no": "2026001", "name": "新姓名", "class_code": "A2"}],
        purpose="INCREMENTAL",
    )
    assert plan["rows"][0]["action"] == "TRANSFER_REQUIRES_CHANGE"
    service.confirm(2, int(plan["id"]), plan["lock_version"])
    assert school.get(Student, 1).administrative_class_id == 1
    assert school.get(Student, 1).name == "样例学生"


def test_full_compare_missing_students_are_candidates_only(school):
    from app.modules.importer.student_data_service import StudentDataService

    service = StudentDataService(school)
    plan = service.preview(2, college_id=1, rows=[], purpose="FULL_COMPARE")
    assert plan["missing_student_ids"] == ["1"]
    service.confirm(2, int(plan["id"]), plan["lock_version"])
    assert school.get(Student, 1).status == "ACTIVE"


def test_stale_import_rolls_back_entire_batch(school):
    from app.modules.importer.student_data_service import StudentDataService

    service = StudentDataService(school)
    plan = service.preview(
        2,
        college_id=1,
        rows=[
            {"student_no": "2026001", "name": "新姓名", "class_code": "A1"},
            {"student_no": "2026002", "name": "新学生", "class_code": "A1"},
        ],
        purpose="INCREMENTAL",
    )
    EnrollmentService(school, today=date(2026, 10, 14)).commit(2, 1, change(), request_id=None)
    with pytest.raises(ConflictError):
        service.confirm(2, int(plan["id"]), plan["lock_version"])
    school.rollback()
    assert school.scalar(select(Student).where(Student.student_no == "2026002")) is None


def test_export_roundtrip_carries_stable_class_number_and_versions(school):
    import io

    from app.modules.importer.student_data_service import StudentDataService
    from openpyxl import load_workbook

    service = StudentDataService(school)
    data = service.export(2, 1)
    workbook = load_workbook(io.BytesIO(data), read_only=True)
    headers = list(next(workbook.active.values))
    assert {"student_no", "class_code", "student_id", "lock_version", "source_as_of"} <= set(
        headers
    )
    plan = service.preview_file(2, 1, data, purpose="INCREMENTAL")
    assert plan["rows"][0]["action"] == "UNCHANGED"


def test_zip_handoff_combines_all_files_before_confirmation(school):
    import io
    import zipfile

    from app.modules.importer.student_data_service import StudentDataService

    service = StudentDataService(school)
    template = service.export(2, 1)
    original_name = school.get(Student, 1).name
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("班级1.xlsx", template)
        archive.writestr("班级2.xlsx", template)
    plan = service.preview_file(2, 1, content.getvalue())
    assert any(e["code"] == "DUPLICATE_STUDENT_NO" for e in plan["errors"])
    with pytest.raises(ConflictError):
        service.confirm(2, int(plan["id"]), plan["lock_version"])
    assert school.get(Student, 1).name == original_name


def test_new_student_import_updates_future_class_roster_once(school):
    from app.modules.importer.student_data_service import StudentDataService
    from app.modules.inspection.models import InspectionTask

    add_courses(school)
    school.add(
        InspectionTask(
            id=100,
            task_key="new-member",
            college_id=1,
            semester_id=1,
            inspection_date=date(2026, 11, 2),
            week_no=1,
            inspection_type="COURSE",
            start_period=1,
            end_period=2,
            teaching_class_id=1,
            expected_count_current=0,
        )
    )
    school.commit()
    service = StudentDataService(school)
    plan = service.preview(
        2,
        college_id=1,
        rows=[{"student_no": "NEW_IMPORT", "name": "新增模拟学生", "class_code": "A1"}],
    )
    result = service.confirm(2, int(plan["id"]), plan["lock_version"])
    task = school.get(InspectionTask, 100)
    assert task.roster_version == 2
    assert task.expected_count_current == 2
    assert result["task_refresh"]["refreshed_task_ids"] == ["100"]


def add_courses(db):
    from app.modules.academic.enrollment_models import TeachingClassAudience
    from app.modules.academic.models import Course, Semester, TeachingClass, TeachingClassStudent

    db.add(
        Semester(
            id=1,
            code="2026",
            name="2026",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
            first_monday=date(2026, 8, 31),
        )
    )
    db.add(Course(id=1, course_code="C1", course_name="普通课程"))
    db.flush()
    for tid in [1, 2, 3]:
        db.add(
            TeachingClass(
                id=tid,
                semester_id=1,
                course_id=1,
                college_id=1,
                class_code=f"T{tid}",
                class_name=f"教学班{tid}",
            )
        )
    db.flush()
    db.add_all(
        [
            TeachingClassAudience(teaching_class_id=1, administrative_class_id=1),
            TeachingClassAudience(teaching_class_id=2, administrative_class_id=2),
            TeachingClassStudent(teaching_class_id=1, student_id=1),
            TeachingClassStudent(teaching_class_id=3, student_id=1),
        ]
    )
    db.commit()


def test_dated_common_courses_follow_transfer_but_electives_remain(school):
    from app.modules.academic.participation import roster_at

    add_courses(school)
    service = EnrollmentService(school, today=date(2026, 10, 14))
    service.commit(2, 1, change(when=date(2026, 11, 1)), request_id=None)
    assert [s.id for s in roster_at(school, 1, date(2026, 10, 31))] == [1]
    assert roster_at(school, 1, date(2026, 11, 1)) == []
    assert [s.id for s in roster_at(school, 2, date(2026, 11, 1))] == [1]
    assert [s.id for s in roster_at(school, 3, date(2026, 11, 1))] == [1]


def test_future_tasks_revised_with_history_preserved(school):
    from app.modules.inspection.models import InspectionTask, TaskRosterMember

    add_courses(school)
    for tid, when in [(1, date(2026, 9, 1)), (2, date(2026, 11, 2))]:
        school.add(
            InspectionTask(
                id=tid,
                task_key=f"task{tid}",
                college_id=1,
                semester_id=1,
                inspection_date=when,
                week_no=1,
                inspection_type="COURSE",
                start_period=1,
                end_period=2,
                teaching_class_id=1,
                expected_count_snapshot=1,
                expected_count_current=1,
            )
        )
    school.flush()
    for tid in [1, 2]:
        school.add(
            TaskRosterMember(
                task_id=tid,
                roster_version=1,
                student_id=1,
                student_no="2026001",
                name="旧姓名",
                class_name_snapshot="A1",
            )
        )
    school.commit()
    result = EnrollmentService(school, today=date(2026, 10, 14)).commit(
        2, 1, change(when=date(2026, 11, 1)), request_id=None
    )
    assert result["impact"]["refreshed_task_ids"] == ["2"]
    assert school.get(InspectionTask, 1).roster_version == 1
    assert school.get(InspectionTask, 2).roster_version == 2
    assert school.get(InspectionTask, 2).expected_count_current == 0
    assert len(list(school.scalars(select(TaskRosterMember)))) == 2


def test_teacher_binding_and_manager_functions_use_fixed_college(school):
    from app.modules.academic.college_service import CollegeService
    from app.modules.identity.service import IdentityService

    colleges = CollegeService(school)
    assert [c["id"] for c in colleges.list(2)] == ["1"]
    IdentityService(school).assign_roles(
        actor_user_id=2,
        target_user_id=3,
        desired_codes=["STUDENT", "STUDENT_AFFAIRS_MANAGER"],
        expected_version=0,
        reason=None,
        request_id=None,
    )
    functions = colleges.manager_functions(2, 3)
    assert functions["college_id"] == "1"
    updated = colleges.set_manager_functions(
        2, 3, ["attendance.read"], functions["lock_version"], request_id=None
    )
    assert updated["allowed_actions"] == ["attendance.read"]
    assert "inspection.generate" not in IdentityRepository(school).list_effective_permissions(3)
    with pytest.raises(PermissionDeniedError):
        colleges.set_teacher_college(2, 2, 2, 0, request_id=None)


def test_elective_future_snapshot_changes_without_overwriting_manual_count(school):
    from app.modules.inspection.models import InspectionTask, TaskRosterMember

    add_courses(school)
    school.add(
        InspectionTask(
            id=10,
            task_key="elective",
            college_id=1,
            semester_id=1,
            inspection_date=date(2026, 11, 2),
            week_no=1,
            inspection_type="COURSE",
            start_period=1,
            end_period=2,
            teaching_class_id=3,
            expected_count_current=8,
        )
    )
    school.flush()
    school.add(
        TaskRosterMember(
            task_id=10,
            roster_version=1,
            student_id=1,
            student_no="2026001",
            name="旧姓名",
            administrative_class_id_snapshot=1,
        )
    )
    school.commit()
    EnrollmentService(school, today=date(2026, 10, 14)).commit(
        2, 1, change(when=date(2026, 11, 1)), request_id=None
    )
    task = school.get(InspectionTask, 10)
    assert task.roster_version == 2
    assert task.expected_count_current == 8
    latest = school.scalar(
        select(TaskRosterMember).where(
            TaskRosterMember.task_id == 10, TaskRosterMember.roster_version == 2
        )
    )
    assert latest.administrative_class_id_snapshot == 2


def test_membership_change_preserves_manual_count_and_requires_review(school):
    from app.modules.inspection.models import InspectionTask, TaskRosterMember

    add_courses(school)
    school.add(
        InspectionTask(
            id=10,
            task_key="common",
            college_id=1,
            semester_id=1,
            inspection_date=date(2026, 11, 2),
            week_no=1,
            inspection_type="COURSE",
            start_period=1,
            end_period=2,
            teaching_class_id=1,
            expected_count_current=8,
        )
    )
    school.flush()
    school.add(
        TaskRosterMember(
            task_id=10, roster_version=1, student_id=1, student_no="2026001", name="旧姓名"
        )
    )
    school.commit()
    EnrollmentService(school, today=date(2026, 10, 14)).commit(
        2, 1, change(when=date(2026, 11, 1)), request_id=None
    )
    task = school.get(InspectionTask, 10)
    assert task.expected_count_current == 8
    assert task.expected_count_review_required


def test_scheduled_cross_college_transfer_stops_old_manager_permissions_on_date(
    school, monkeypatch
):
    import app.modules.identity.authorization as authorization
    from app.modules.identity.repository import IdentityRepository
    from app.modules.identity.service import IdentityService

    monkeypatch.setattr(authorization, "business_today", lambda: date(2026, 10, 14))
    IdentityService(school).assign_roles(
        actor_user_id=2,
        target_user_id=3,
        desired_codes=["STUDENT", "STUDENT_AFFAIRS_MANAGER"],
        expected_version=0,
        reason=None,
        request_id=None,
    )
    EnrollmentService(school, today=date(2026, 10, 14)).commit(
        1, 1, change(target=3, when=date(2026, 11, 1)), request_id=None
    )
    assert "inspection.generate" in IdentityRepository(school).list_effective_permissions(3)
    monkeypatch.setattr(authorization, "business_today", lambda: date(2026, 11, 1))
    assert "inspection.generate" not in IdentityRepository(school).list_effective_permissions(3)
    assert "attendance.read" in IdentityRepository(school).list_effective_permissions(3)
