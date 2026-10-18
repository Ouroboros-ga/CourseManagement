"""回归：导入人员匹配不得用学院范围掩盖身份冲突。"""

import pytest
from app.modules.academic.models import AdministrativeClass
from app.modules.academic.staff_models import ClassStaffResponsibility, FacultyStaff
from sqlalchemy import select

from tests.unit.test_staff_importer import setup_env, sheet


@pytest.fixture(name="campus")
def configured():
    from tests.unit.test_campus_configuration import campus as campus_fixture

    yield from campus_fixture.__wrapped__()


def _responsibility_preview(service, actor, content):
    return service.create_preview(
        actor,
        target="class_responsibility",
        content=content,
        semester_id=None,
        teaching_class_id=None,
        filename="责任表.xlsx",
        replace=False,
        request_id=None,
    )


def test_existing_student_number_with_different_name_requires_explicit_archive_correction(campus):
    from app.modules.academic.models import Student
    from app.modules.importer.confirmation_set import ImportConfirmationSet

    service, db, actor, college_a, _, _ = setup_env(campus)
    ac = AdministrativeClass(class_code="NAME01", class_name="姓名核对班", college_id=college_a)
    db.add(ac)
    db.flush()
    db.add(Student(student_no="0012345678", name="原姓名", administrative_class_id=ac.id))
    db.commit()
    preview = service.create_preview(
        actor,
        target="admin_roster",
        content=sheet([["学号", "姓名", "班级"], ["0012345678", "另一姓名", ac.class_name]]),
        semester_id=None,
        teaching_class_id=None,
        filename="学生.xlsx",
        replace=False,
        request_id=None,
    )
    plan = ImportConfirmationSet(service).preview([int(preview.id)])
    assert not plan["can_confirm"]
    assert any("姓名" in issue["message"] for file in plan["files"] for issue in file["issues"])
    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.confirm(actor, int(preview.id), None)


def test_existing_staff_number_with_different_name_is_not_silently_renamed(campus):
    from app.modules.importer.confirmation_set import ImportConfirmationSet

    service, db, actor, college_a, _, _ = setup_env(campus)
    db.add(
        FacultyStaff(
            school_id=campus[4]["school_id"],
            college_id=college_a,
            staff_no="00123",
            name="原教师",
            status="ACTIVE",
        )
    )
    db.commit()
    preview = service.create_preview(
        actor,
        target="faculty_staff",
        content=sheet([["工号", "姓名"], ["00123", "另一教师"]]),
        semester_id=None,
        teaching_class_id=None,
        filename="教师.xlsx",
        replace=False,
        request_id=None,
    )
    assert not ImportConfirmationSet(service).preview([int(preview.id)])["can_confirm"]
    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.confirm(actor, int(preview.id), None)


def test_responsibility_name_only_across_colleges_is_ambiguous(campus):
    service, db, actor, college_a, college_b, _ = setup_env(campus)
    school_id = campus[4]["school_id"]
    ac = AdministrativeClass(
        class_code="IDENTITY_A1", class_name="身份冲突班", college_id=college_a, status="ACTIVE"
    )
    db.add_all(
        [
            ac,
            FacultyStaff(
                school_id=school_id,
                college_id=college_a,
                staff_no="ID-A",
                name="同名教师",
                status="ACTIVE",
            ),
            FacultyStaff(
                school_id=school_id,
                college_id=college_b,
                staff_no="ID-B",
                name="同名教师",
                status="ACTIVE",
            ),
        ]
    )
    db.commit()

    preview = _responsibility_preview(
        service, actor, sheet([["行政班", "班主任姓名"], [ac.class_name, "同名教师"]])
    )

    assert not preview.can_confirm
    assert any(issue.get("code") == "STAFF_NAME_AMBIGUOUS" for issue in preview.errors), (
        preview.errors
    )
    assert db.scalar(select(ClassStaffResponsibility)) is None


def test_responsibility_explicit_number_resolves_cross_college_name(campus):
    service, db, actor, college_a, college_b, _ = setup_env(campus)
    school_id = campus[4]["school_id"]
    ac = AdministrativeClass(
        class_code="IDENTITY_A2", class_name="身份确认班", college_id=college_a, status="ACTIVE"
    )
    chosen = FacultyStaff(
        school_id=school_id, college_id=college_a, staff_no="ID-A", name="同名教师", status="ACTIVE"
    )
    duplicate = FacultyStaff(
        school_id=school_id, college_id=college_b, staff_no="ID-B", name="同名教师", status="ACTIVE"
    )
    db.add_all([ac, chosen, duplicate])
    db.commit()

    preview = _responsibility_preview(
        service,
        actor,
        sheet(
            [["行政班", "班主任工号", "班主任姓名"], [ac.class_name, chosen.staff_no, chosen.name]]
        ),
    )

    assert preview.can_confirm, preview.errors
    assert not any(issue.get("code") == "STAFF_NAME_AMBIGUOUS" for issue in preview.errors)


def test_responsibility_number_name_mismatch_is_blocked(campus):
    service, db, actor, college_a, _, _ = setup_env(campus)
    school_id = campus[4]["school_id"]
    ac = AdministrativeClass(
        class_code="IDENTITY_A3", class_name="身份矛盾班", college_id=college_a, status="ACTIVE"
    )
    db.add_all(
        [
            ac,
            FacultyStaff(
                school_id=school_id,
                college_id=college_a,
                staff_no="ID-A",
                name="甲教师",
                status="ACTIVE",
            ),
            FacultyStaff(
                school_id=school_id,
                college_id=college_a,
                staff_no="ID-B",
                name="乙教师",
                status="ACTIVE",
            ),
        ]
    )
    db.commit()

    preview = _responsibility_preview(
        service,
        actor,
        sheet([["行政班", "班主任工号", "班主任姓名"], [ac.class_name, "ID-A", "乙教师"]]),
    )

    assert not preview.can_confirm
    assert any(
        "姓名" in issue["message"] and "不符" in issue["message"] for issue in preview.errors
    ), preview.errors


def test_teaching_name_only_duplicate_remains_unlinked_pending(campus):
    """授课表的姓名匹配保持待确认语义，不因授权学院优先而自动选人。"""
    from app.modules.importer.person_links import match_staff

    service, db, _, college_a, college_b, _ = setup_env(campus)
    school_id = campus[4]["school_id"]
    a = FacultyStaff(
        school_id=school_id,
        college_id=college_a,
        staff_no="TEACH-A",
        name="授课同名",
        status="ACTIVE",
    )
    b = FacultyStaff(
        school_id=school_id,
        college_id=college_b,
        staff_no="TEACH-B",
        name="授课同名",
        status="ACTIVE",
    )
    db.add_all([a, b])
    db.commit()

    profiles = db.scalars(select(FacultyStaff).where(FacultyStaff.school_id == school_id)).all()
    resolved, problem = match_staff(profiles, "授课同名")

    assert resolved is None
    assert problem
