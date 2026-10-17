"""教职工资源授权边界；仅使用独立内存库，不读取运行库配置。"""

from datetime import date

import pytest
from app.models import Base
from app.modules.academic.models import AdministrativeClass, Course, Semester, TeachingClass
from app.modules.academic.offering_models import AcademicOffering
from app.modules.identity.models import UserAccount
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def staff_db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(School(id=1, code="S", name="学校"))
        db.flush()
        db.add_all([College(id=i, school_id=1, code=str(i), name=str(i)) for i in (1, 2)])
        db.add(UserAccount(id=1, display_name="同名教师", status="ACTIVE"))
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
        for i in (1, 2):
            db.add(Course(id=i, college_id=i, course_code="M", course_name="数学"))
        db.flush()
        for i in (1, 2):
            db.add(
                TeachingClass(
                    id=i,
                    college_id=i,
                    semester_id=1,
                    course_id=i,
                    class_code=str(i),
                    class_name="数学",
                    teacher_name="同名教师",
                    academic_offering_id="shared",
                )
            )
        db.add(AdministrativeClass(id=1, college_id=1, class_code="A", class_name="一班"))
        db.commit()
        yield db
    engine.dispose()


def add_staff(db):
    from app.modules.academic.staff_models import FacultyStaff

    staff = FacultyStaff(school_id=1, college_id=1, staff_no="00001", name="同名教师", user_id=1)
    db.add(staff)
    db.flush()
    return staff


def visible_teaching(db, *, today=date(2026, 10, 17), course_day=date(2026, 10, 10)):
    from app.modules.identity.staff_scope import teaching_class_condition

    return list(
        db.scalars(
            select(TeachingClass.id)
            .where(teaching_class_condition(1, occurrence_on=course_day, as_of=today))
            .order_by(TeachingClass.id)
        )
    )


def test_names_never_authorize_and_local_anchor_does_not_expand_to_shared_views(staff_db):
    from app.modules.academic.staff_models import TeachingStaffAssignment

    db = staff_db
    assert visible_teaching(db) == []
    staff = add_staff(db)
    db.add(
        TeachingStaffAssignment(
            staff_id=staff.id,
            semester_id=1,
            anchor_type="LOCAL",
            teaching_class_id=1,
            effective_from=date(2026, 9, 1),
        )
    )
    db.commit()
    assert visible_teaching(db) == [1]
    assert staff.staff_no == "00001"


def test_shared_anchor_and_next_query_revocation_use_fresh_database_facts(staff_db):
    from app.modules.academic.staff_models import FacultyStaff, TeachingStaffAssignment

    db = staff_db
    staff = add_staff(db)
    relation = TeachingStaffAssignment(
        staff_id=staff.id,
        semester_id=1,
        anchor_type="SHARED",
        academic_offering_id="shared",
        effective_from=date(2026, 9, 1),
    )
    db.add(relation)
    db.commit()
    assert visible_teaching(db) == [1, 2]
    db.execute(update(FacultyStaff).values(status="INACTIVE"))
    assert visible_teaching(db) == []
    db.execute(update(FacultyStaff).values(status="ACTIVE"))
    db.execute(update(UserAccount).values(status="DISABLED"))
    assert visible_teaching(db) == []
    db.execute(update(UserAccount).values(status="ACTIVE"))
    relation.effective_to = date(2026, 10, 17)
    db.flush()
    assert visible_teaching(db) == []
    assert visible_teaching(db, today=date(2026, 10, 16)) == [1, 2]
    assert visible_teaching(db, today=date(2026, 10, 16), course_day=date(2026, 8, 31)) == []


@pytest.mark.parametrize(
    "anchor,local,shared", [("LOCAL", None, None), ("LOCAL", 1, "shared"), ("SHARED", 1, None)]
)
def test_database_rejects_ambiguous_authorization_anchor(staff_db, anchor, local, shared):
    from app.modules.academic.staff_models import TeachingStaffAssignment

    staff = add_staff(staff_db)
    staff_db.add(
        TeachingStaffAssignment(
            staff_id=staff.id,
            semester_id=1,
            anchor_type=anchor,
            teaching_class_id=local,
            academic_offering_id=shared,
            effective_from=date(2026, 9, 1),
        )
    )
    with pytest.raises(IntegrityError):
        staff_db.flush()


def test_responsibility_does_not_grant_foreign_college_review(staff_db):
    from app.modules.academic.staff_models import ClassStaffResponsibility
    from app.modules.identity.staff_scope import responsible_class_condition

    db = staff_db
    staff = add_staff(db)
    db.add(
        ClassStaffResponsibility(
            staff_id=staff.id,
            administrative_class_id=1,
            duty="COUNSELOR",
            effective_from=date(2026, 9, 1),
        )
    )
    db.commit()

    def visible(task_college_id):
        return list(
            db.scalars(
                select(AdministrativeClass.id).where(
                    responsible_class_condition(
                        1,
                        administrative_class_id=AdministrativeClass.id,
                        as_of=date(2026, 10, 17),
                        review_college_id=task_college_id,
                    )
                )
            )
        )

    assert visible(1) == [1]
    assert visible(2) == []
    assert visible(None) == [1]  # 只读范围不等于审核或材料访问授权。


def test_semester_unbinding_and_unconfirmed_mapping_fail_closed(staff_db):
    from app.modules.academic.staff_models import TeachingStaffAssignment

    db = staff_db
    staff = add_staff(db)
    db.add(
        TeachingStaffAssignment(
            staff_id=staff.id,
            semester_id=1,
            anchor_type="SHARED",
            academic_offering_id="shared",
            effective_from=date(2026, 9, 1),
        )
    )
    db.commit()
    db.add(
        Semester(
            id=2,
            code="S",
            name="春",
            start_date=date(2027, 2, 1),
            end_date=date(2027, 7, 1),
            first_monday=date(2027, 2, 1),
            total_weeks=22,
        )
    )
    db.flush()
    db.execute(update(TeachingStaffAssignment).values(semester_id=2))
    assert visible_teaching(db) == []
    db.execute(update(TeachingStaffAssignment).values(semester_id=1))
    # 停用学院不能通过共享身份继续暴露教学班。
    from app.modules.academic.staff_models import FacultyStaff

    db.execute(update(College).where(College.id == 2).values(status="INACTIVE"))
    assert visible_teaching(db) == [1]
    db.execute(update(FacultyStaff).values(user_id=None))
    assert visible_teaching(db) == []
    db.execute(update(FacultyStaff).values(user_id=1))
    db.execute(update(TeachingClass).values(academic_offering_id=None))
    assert visible_teaching(db) == []
