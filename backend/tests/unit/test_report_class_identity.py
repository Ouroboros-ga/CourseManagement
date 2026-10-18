from datetime import timedelta

from app.modules.academic.models import AdministrativeClass, Student
from app.modules.academic.staff_models import ClassStaffResponsibility, FacultyStaff
from app.modules.identity.role_scope import business_today
from app.modules.inspection.models import TaskRosterMember
from app.modules.report.aggregation import build_classes
from app.modules.report.repository import ReportRepository
from sqlalchemy import select

from tests.unit.test_scoped_attendance import attendance_fixture, prepare  # noqa: F401


def test_same_named_classes_remain_separate_by_frozen_ids_not_current_student_class(campus):
    db, _, a, b, own, other = prepare(campus)
    classes = list(
        db.scalars(
            select(AdministrativeClass).where(
                AdministrativeClass.college_id.in_([int(a["id"]), int(b["id"])])
            )
        )
    )
    for record, college, ac in zip([own, other], [a, b], classes, strict=True):
        ac.class_name = "同名班"
        student = db.get(Student, record.student_id)
        db.add(
            TaskRosterMember(
                task_id=record.task_id,
                roster_version=1,
                student_id=student.id,
                student_no=student.student_no,
                name=student.name,
                class_name_snapshot="同名班",
                administrative_class_id_snapshot=ac.id,
                college_id_snapshot=int(college["id"]),
            )
        )
    db.commit()
    # 当前学籍改变不影响冻结分组。
    db.get(Student, own.student_id).administrative_class_id = classes[1].id
    db.commit()
    repo = ReportRepository(db)
    ids = [own.task_id, other.task_id]
    result = build_classes(
        {tid: (1, 1) for tid in ids},
        repo.roster_counts_by_task_class(ids),
        repo.attendance_counts_by_task_class(ids),
    )
    assert len(result) == 2
    assert {r.class_id for r in result} == {str(c.id) for c in classes}
    assert sorted(r.abnormal_count for r in result) == [1, 1]
    assert {r.college_id for r in result} == {a["id"], b["id"]}
    assert repo.task_meta(ids)[own.task_id]["administrative_class_ids"] == [classes[0].id]
    details = repo.abnormal_details(ids)
    assert {r["administrative_class_id_snapshot"] for r in details} == {str(c.id) for c in classes}
    assert {r["student_id"] for r in details} == {str(own.student_id), str(other.student_id)}


def test_ambiguous_legacy_class_name_never_guesses_a_class_id(campus):
    db, _, a, b, _, _ = prepare(campus)
    for ac in db.scalars(
        select(AdministrativeClass).where(
            AdministrativeClass.college_id.in_([int(a["id"]), int(b["id"])])
        )
    ):
        ac.class_name = "同名班"
    db.commit()
    duties = ReportRepository(db).class_duties_map({"同名班"})
    assert duties.get("同名班", (None, None, None))[2] is None


def test_report_responsibility_comes_from_effective_relationship_not_legacy_text(campus):
    from app.modules.report.class_identity import ClassIdentity

    db, _, a, _, _, _ = prepare(campus)
    ac = db.scalar(
        select(AdministrativeClass).where(AdministrativeClass.college_id == int(a["id"]))
    )
    ac.head_teacher = "过期文字"
    staff = FacultyStaff(
        school_id=int(a["school_id"]),
        college_id=int(a["id"]),
        staff_no="0001",
        name="真实负责人",
        status="ACTIVE",
    )
    db.add(staff)
    db.flush()
    db.add(
        ClassStaffResponsibility(
            staff_id=staff.id,
            administrative_class_id=ac.id,
            duty="HEAD_TEACHER",
            effective_from=business_today() - timedelta(days=10),
            lock_version=1,
        )
    )
    db.commit()
    key = ClassIdentity.from_snapshot(int(a["id"]), ac.id, ac.class_name)
    duties = ReportRepository(db).class_duties_map({key})
    assert duties[key][0] == staff.name
