from datetime import timedelta

import pytest
from app.core.exceptions import ConflictError
from app.modules.academic.models import AdministrativeClass, Semester, TeachingClass
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.identity.role_scope import business_today
from app.modules.importer.confirmation_set import ImportConfirmationSet
from sqlalchemy import select

from tests.unit.test_staff_importer import configured, setup_env, sheet  # noqa: F401


def prepare(campus):
    service, db, actor, cid, other, sid = setup_env(campus)
    semester = db.get(Semester, sid)
    semester.start_date = business_today() - timedelta(days=7)
    semester.end_date = business_today() + timedelta(days=100)
    staff = FacultyStaff(
        school_id=campus[4]["school_id"],
        college_id=cid,
        staff_no="001001",
        name="张老师",
        status="ACTIVE",
    )
    db.add(staff)
    db.commit()
    return service, db, actor, cid, other, sid, staff


def upload(service, sid, name="张老师", number=""):
    return service.create_preview(
        service.actor,
        target="timetable",
        semester_id=sid,
        teaching_class_id=None,
        filename="课程.xlsx",
        replace=False,
        request_id=None,
        content=sheet(
            [
                [
                    "教学班码",
                    "课程代码",
                    "课程名称",
                    "星期",
                    "开始大节",
                    "结束大节",
                    "周次",
                    "任课教师",
                    "教师工号",
                ],
                ["NEW_CLASS", "NEW_COURSE", "测试课程", "1", "1", "1", "1", name, number],
            ]
        ),
    )


def confirm(service, preview):
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    assert plan["can_confirm"], plan
    return wizard.confirm([int(preview.id)], plan["revision"], None)


def test_timetable_confirmation_creates_relation_without_account_and_reimport_is_idempotent(campus):
    service, db, _, _, _, sid, staff = prepare(campus)
    preview = upload(service, sid)
    assert db.scalar(select(TeachingStaffAssignment)) is None
    assert preview.summary["person_links_create"] == 1
    result = confirm(service, preview)
    assert result["files"][0]["summary"]["person_links_created"] == 1
    relation = db.scalar(select(TeachingStaffAssignment))
    assert relation.staff_id == staff.id and staff.user_id is None
    assert db.get(TeachingClass, relation.teaching_class_id).class_code == "NEW_CLASS"
    original = (relation.id, relation.effective_from, relation.effective_to, relation.lock_version)
    confirm(service, upload(service, sid))
    assert (
        relation.id,
        relation.effective_from,
        relation.effective_to,
        relation.lock_version,
    ) == original
    assert len(db.scalars(select(TeachingStaffAssignment)).all()) == 1


def test_school_wide_duplicate_name_is_pending_but_staff_number_resolves_it(campus):
    service, db, _, _, other, sid, staff = prepare(campus)
    db.add(
        FacultyStaff(
            school_id=staff.school_id,
            college_id=other,
            staff_no="002001",
            name=staff.name,
            status="ACTIVE",
        )
    )
    db.commit()
    preview = upload(service, sid)
    assert preview.can_confirm
    assert preview.summary["person_links_pending"] == 1
    confirm(service, preview)
    assert db.scalar(select(TeachingStaffAssignment)) is None
    confirm(service, upload(service, sid, number="001001"))
    assert db.scalar(select(TeachingStaffAssignment.staff_id)) == staff.id


def test_people_change_invalidates_review_before_any_course_is_written(campus):
    service, db, _, _, _, sid, staff = prepare(campus)
    preview = upload(service, sid)
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    staff.status = "INACTIVE"
    staff.lock_version += 1
    db.commit()
    with pytest.raises(ConflictError):
        wizard.confirm([int(preview.id)], plan["revision"], None)
    assert db.scalar(select(TeachingClass).where(TeachingClass.class_code == "NEW_CLASS")) is None


def test_legacy_duty_sheet_creates_real_responsibility_in_same_confirmation(campus):
    service, db, actor, _, _, _, staff = prepare(campus)
    ac = db.scalar(select(AdministrativeClass).where(AdministrativeClass.college_id == service.cid))
    preview = service.create_preview(
        actor,
        target="class_duty",
        semester_id=None,
        teaching_class_id=None,
        filename="班主任责任表.xlsx",
        replace=False,
        request_id=None,
        content=sheet([["行政班", "班主任", "辅导员"], [ac.class_name, staff.name, staff.name]]),
    )
    assert preview.can_confirm, preview.errors
    assert db.scalar(select(ClassStaffResponsibility)) is None
    confirm(service, preview)
    duties = db.scalars(select(ClassStaffResponsibility)).all()
    assert {(r.staff_id, r.administrative_class_id, r.duty) for r in duties} == {
        (staff.id, ac.id, "HEAD_TEACHER"),
        (staff.id, ac.id, "COUNSELOR"),
    }


def test_existing_courses_can_be_reconciled_after_late_staff_archive_without_reupload(campus):
    from app.modules.importer.person_reconciliation import PersonLinkReconciliation

    service, db, _, cid, _, sid, staff = prepare(campus)
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == cid))
    tc.teacher_name = staff.name
    db.commit()
    reconcile = PersonLinkReconciliation(service)
    plan = reconcile.preview("teaching", sid)
    assert plan["summary"]["person_links_create"] == 1
    assert db.scalar(select(TeachingStaffAssignment)) is None
    result = reconcile.confirm("teaching", sid, plan["revision"], None)
    assert result["person_links_created"] == 1
    fresh = reconcile.preview("teaching", sid)
    assert fresh["summary"]["person_links_create"] == 0
    assert fresh["summary"]["person_links_existing"] == 1


def test_reconciliation_conflict_and_explicitly_ended_relationship_do_not_restore_authority(campus):
    from app.modules.importer.person_reconciliation import PersonLinkReconciliation

    service, db, _, cid, _, sid, staff = prepare(campus)
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == cid))
    tc.teacher_name = staff.name
    db.commit()
    reconcile = PersonLinkReconciliation(service)
    plan = reconcile.preview("teaching", sid)
    staff.name = "更名后的教师"
    staff.lock_version += 1
    db.commit()
    with pytest.raises(ConflictError):
        reconcile.confirm("teaching", sid, plan["revision"], None)
    assert db.scalar(select(TeachingStaffAssignment)) is None
    tc.teacher_name = staff.name
    db.add(
        TeachingStaffAssignment(
            staff_id=staff.id,
            semester_id=sid,
            anchor_type="LOCAL",
            teaching_class_id=tc.id,
            effective_from=business_today() - timedelta(days=5),
            effective_to=business_today() - timedelta(days=1),
            lock_version=1,
        )
    )
    db.commit()
    plan = reconcile.preview("teaching", sid)
    assert plan["summary"]["person_links_pending"] == 1
    assert plan["summary"]["person_links_create"] == 0


def test_two_files_same_teacher_relation_is_only_created_once(campus):
    service, db, actor, _, _, sid, _ = prepare(campus)
    first = upload(service, sid)
    second = service.create_preview(
        actor,
        target="timetable",
        semester_id=sid,
        teaching_class_id=None,
        filename="课程2.xlsx",
        replace=False,
        request_id=None,
        content=sheet(
            [
                [
                    "教学班码",
                    "课程代码",
                    "课程名称",
                    "星期",
                    "开始大节",
                    "结束大节",
                    "周次",
                    "任课教师",
                ],
                ["NEW_CLASS", "NEW_COURSE", "测试课程", "2", "1", "1", "1", "张老师"],
            ]
        ),
    )
    wizard = ImportConfirmationSet(service)
    ids = [int(first.id), int(second.id)]
    plan = wizard.preview(ids)
    assert plan["can_confirm"], plan
    wizard.confirm(ids, plan["revision"], None)
    assert len(db.scalars(select(TeachingStaffAssignment)).all()) == 1


def test_cross_college_lecturer_relation_is_managed_by_course_college(campus):
    from app.core.exceptions import NotFoundError
    from app.modules.academic.staff_service import StaffManagementService

    service, db, _, cid, other, sid, staff = prepare(campus)
    staff.college_id = other
    db.commit()
    confirm(service, upload(service, sid, number=staff.staff_no))
    relation = db.scalar(select(TeachingStaffAssignment))
    course_owner = StaffManagementService(db, campus[2], cid)
    staff_owner = StaffManagementService(db, campus[2], other)
    assert [r["id"] for r in course_owner.list_teaching_assignments()] == [str(relation.id)]
    assert staff_owner.list_teaching_assignments() == []
    with pytest.raises(NotFoundError):
        staff_owner.end_teaching_assignment(
            relation.id,
            {"effective_to": str(business_today() + timedelta(days=1)), "lock_version": 1},
        )
    course_owner.end_teaching_assignment(
        relation.id, {"effective_to": str(business_today() + timedelta(days=1)), "lock_version": 1}
    )


def test_conflicting_duties_in_same_file_never_choose_last_person(campus):
    service, db, actor, cid, _, _, staff = prepare(campus)
    db.add(
        FacultyStaff(
            school_id=staff.school_id,
            college_id=cid,
            staff_no="009",
            name="李老师",
            status="ACTIVE",
        )
    )
    db.commit()
    ac = db.scalar(select(AdministrativeClass).where(AdministrativeClass.college_id == cid))
    preview = service.create_preview(
        actor,
        target="class_duty",
        semester_id=None,
        teaching_class_id=None,
        filename="责任表.xlsx",
        replace=False,
        request_id=None,
        content=sheet(
            [["行政班", "班主任"], [ac.class_name, staff.name], [ac.class_name, "李老师"]]
        ),
    )
    assert preview.summary["person_links_pending"] == 2
    plan = ImportConfirmationSet(service).preview([int(preview.id)])
    assert not plan["can_confirm"]  # 两个不同的班级显示值也应阻断，不允许最后一行覆盖。
    assert db.scalar(select(ClassStaffResponsibility)) is None


def test_duty_number_only_preserves_leading_zeros_and_resolves_duplicate_names(campus):
    service, db, actor, cid, _, _, staff = prepare(campus)
    db.add(
        FacultyStaff(
            school_id=staff.school_id,
            college_id=cid,
            staff_no="009",
            name=staff.name,
            status="ACTIVE",
        )
    )
    db.commit()
    ac = db.scalar(select(AdministrativeClass).where(AdministrativeClass.college_id == cid))
    preview = service.create_preview(
        actor,
        target="class_duty",
        semester_id=None,
        teaching_class_id=None,
        filename="责任表.xlsx",
        replace=False,
        request_id=None,
        content=sheet([["行政班", "班主任工号"], [ac.class_name, "001001"]]),
    )
    assert preview.can_confirm
    assert preview.summary["person_links_create"] == 1
    confirm(service, preview)
    assert db.scalar(select(ClassStaffResponsibility.staff_id)) == staff.id


def test_grid_upload_automatically_links_teacher_without_losing_original_periods(
    campus, monkeypatch
):
    from app.core.config import get_settings
    from app.modules.academic.models import CourseSchedule

    from tests.unit.test_scoped_grid_mapping import school_periods

    service, db, actor, cid, _, sid, staff = prepare(campus)
    school_periods(db, sid)
    ac = db.scalar(select(AdministrativeClass).where(AdministrativeClass.college_id == cid))
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", False)
    monkeypatch.setattr(
        "app.modules.importer.service.load_grid",
        lambda _: (
            ac.class_name,
            [
                {
                    "course_name": "网格课程",
                    "weekday": "周一",
                    "weeks": "1-2",
                    "period": "10-11",
                    "location": "测试教室",
                    "teacher": staff.name,
                }
            ],
        ),
    )
    preview = service.create_preview(
        actor,
        target="grid_timetable",
        semester_id=sid,
        teaching_class_id=None,
        filename="班级课表.xls",
        content=b"fixture",
        replace=False,
        request_id=None,
    )
    assert preview.can_confirm, preview.errors
    confirm(service, preview)
    relation = db.scalar(select(TeachingStaffAssignment))
    schedule = db.scalar(
        select(CourseSchedule).where(CourseSchedule.teaching_class_id == relation.teaching_class_id)
    )
    assert (schedule.start_period, schedule.end_period) == (10, 11)
    assert relation.staff_id == staff.id


def test_no_staff_permission_imports_course_but_cannot_grant_staff_relation(campus):
    from tests.unit.test_campus_configuration import grant

    service, db, actor, _, _, sid, _ = prepare(campus)
    config, _, admin, _, college, _ = campus
    for row in config.list_grants(admin, service.cid):
        config.revoke_grant(admin, service.cid, int(row["id"]), row["lock_version"])
    grant(
        config,
        admin,
        actor,
        college,
        ["import.execute", "academic.manage", "course_schedule.import"],
    )
    preview = upload(service, sid)
    assert preview.can_confirm
    assert preview.summary["person_links_create"] == 0
    assert preview.summary["person_links_pending"] == 1
    confirm(service, preview)
    assert (
        db.scalar(select(TeachingClass.id).where(TeachingClass.class_code == "NEW_CLASS"))
        is not None
    )
    assert db.scalar(select(TeachingStaffAssignment)) is None
