"""新确认集合独立于旧逐文件 bulk；只使用隔离数据库夹具。"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError, ConflictError
from app.modules.academic.models import VolunteerQualification
from app.modules.importer.models import ImportBatch
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_importer import prepare, preview


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def wizard(service):
    from app.modules.importer.confirmation_set import ImportConfirmationSet
    return ImportConfirmationSet(service)


def test_preview_does_not_apply_and_confirm_retry_is_idempotent(campus):
    service, db, own, _, sid = prepare(campus)
    draft = preview(service, sid, own.student_no)
    ids = [int(draft.id)]
    plan = wizard(service).preview(ids)
    assert plan["can_confirm"] and plan["files"][0]["changes"][0]["action"] == "CREATE"
    assert db.scalar(select(VolunteerQualification.id)) is None
    result = wizard(service).confirm(ids, plan["revision"], None)
    assert result["status"] == "CONFIRMED"
    assert wizard(service).confirm(ids, plan["revision"], None) == result
    assert len(list(db.scalars(select(VolunteerQualification)))) == 1


def test_blocking_file_rolls_back_other_files_and_keeps_drafts(campus):
    service, db, own, foreign, sid = prepare(campus)
    valid = preview(service, sid, own.student_no)
    invalid = preview(service, sid, foreign.student_no)
    ids = [int(valid.id), int(invalid.id)]
    plan = wizard(service).preview(ids)
    assert not plan["can_confirm"]
    with pytest.raises(AppError):
        wizard(service).confirm(ids, plan["revision"], None)
    assert db.scalar(select(VolunteerQualification.id)) is None
    assert db.get(ImportBatch, int(valid.id)).status == "PREVIEW"


def test_actual_late_apply_error_rolls_back_first_file(campus, monkeypatch):
    from app.modules.academic.models import Student
    service, db, own, _, sid = prepare(campus)
    second_student = Student(student_no="SECOND", name="Second", administrative_class_id=own.administrative_class_id)
    db.add(second_student); db.commit()
    first = preview(service, sid, own.student_no)
    second = preview(service, sid, second_student.student_no)
    ids = [int(first.id), int(second.id)]
    plan = wizard(service).preview(ids)
    original = service._apply_volunteer
    called = 0
    def fail_second(*args, **kwargs):
        nonlocal called
        called += 1
        if called == 2:
            raise ConflictError(message="late failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "_apply_volunteer", fail_second)
    with pytest.raises(ConflictError):
        wizard(service).confirm(ids, plan["revision"], None)
    assert db.scalar(select(VolunteerQualification.id)) is None
    assert all(db.get(ImportBatch, bid).status == "PREVIEW" for bid in ids)


def test_stale_revision_rejects_before_any_official_write(campus):
    service, db, own, _, sid = prepare(campus)
    draft = preview(service, sid, own.student_no)
    ids = [int(draft.id)]
    plan = wizard(service).preview(ids)
    own.name = "Changed after preview"
    db.commit()
    with pytest.raises(ConflictError):
        wizard(service).confirm(ids, plan["revision"], None)
    assert db.scalar(select(VolunteerQualification.id)) is None


def test_expired_preview_returns_conflict_without_formal_write(campus, monkeypatch):
    from datetime import timedelta
    service, db, own, _, sid = prepare(campus)
    draft = preview(service, sid, own.student_no)
    ids = [int(draft.id)]
    plan = wizard(service).preview(ids)
    expiry = db.get(ImportBatch, ids[0]).expires_at
    monkeypatch.setattr("app.modules.importer.confirmation_set.utcnow", lambda: expiry + timedelta(seconds=1))
    with pytest.raises(ConflictError):
        wizard(service).confirm(ids, plan["revision"], None)
    assert db.scalar(select(VolunteerQualification.id)) is None


def test_reupload_unchanged_file_does_not_duplicate_and_preserves_real_source_row(campus):
    from tests.unit.test_scoped_importer import sheet
    service, db, own, _, sid = prepare(campus)
    own.student_no = "00123456"
    db.commit()
    args = dict(target="volunteer", content=sheet([["学号", "是否启用"], [], ["00123456", "是"]]),
                semester_id=sid, teaching_class_id=None, filename="leading-zero.xlsx",
                replace=False, request_id=None)
    for expected_action in ("CREATE", "UNCHANGED"):
        draft = service.create_preview(service.actor, **args)
        ids = [int(draft.id)]
        plan = wizard(service).preview(ids)
        change = plan["files"][0]["changes"][0]
        assert change["key"] == "00123456" and change["source"]["row"] == 3
        assert change["action"] == expected_action
        wizard(service).confirm(ids, plan["revision"], None)
    assert len(list(db.scalars(select(VolunteerQualification)))) == 1


def test_partial_roster_import_keeps_students_missing_from_file(campus):
    from app.modules.academic.models import Student, TeachingClassStudent
    from tests.unit.test_campus_configuration import grant
    from tests.unit.test_scoped_importer import sheet
    service, db, own, _, sid = prepare(campus)
    config, _, admin, teacher, a, _ = campus
    grant(config, admin, teacher, a, ["student.manage"])
    from app.modules.academic.scoped_service import ScopedAcademicService
    from app.common.pagination import PageParams
    assert ScopedAcademicService(db, teacher, int(a["id"])).list_rows("teaching_classes", PageParams(1, 20))["total"] == 1
    from app.modules.academic.models import TeachingClass
    teaching = db.scalar(select(TeachingClass).where(TeachingClass.college_id == service.cid))
    other = Student(student_no="KEEP", name="Keep", administrative_class_id=own.administrative_class_id)
    db.add(other); db.flush()
    db.add(TeachingClassStudent(teaching_class_id=teaching.id, student_id=other.id))
    db.commit()
    draft = service.create_preview(teacher, target="roster", content=sheet([["学号"], [own.student_no]]),
        semester_id=None, teaching_class_id=teaching.id, filename="partial.xlsx", replace=False, request_id=None)
    ids = [int(draft.id)]
    plan = wizard(service).preview(ids)
    wizard(service).confirm(ids, plan["revision"], None)
    assert set(db.scalars(select(TeachingClassStudent.student_id).where(
        TeachingClassStudent.teaching_class_id == teaching.id))) == {own.id, other.id}


def test_timetable_reimport_is_unchanged_and_overlapping_proposals_are_blocked(campus):
    from app.modules.academic.models import CourseSchedule
    from tests.unit.test_campus_configuration import grant
    from tests.unit.test_scoped_importer import sheet
    service, db, _, _, sid = prepare(campus)
    grant(campus[0], campus[2], service.actor, campus[4], ["course_schedule.import"])
    header = ["教学班码", "课程代码", "课程名称", "星期", "开始大节", "结束大节", "周次", "上课地点"]
    row = ["NEW-TC", "NEW-C", "New course", "1", "1", "2", "1-2", "A101"]
    args = dict(target="timetable", semester_id=sid, teaching_class_id=None,
                filename="timetable.xlsx", replace=False, request_id=None)
    for expected in ("CREATE", "UNCHANGED"):
        draft = service.create_preview(service.actor, content=sheet([header, row]), **args)
        ids = [int(draft.id)]
        plan = wizard(service).preview(ids)
        assert plan["can_confirm"]
        assert plan["files"][0]["changes"][0]["action"] == expected, (
            [(s.id, s.college_id, s.teaching_class_id, s.weekday, s.start_period, s.end_period)
             for s in db.scalars(select(CourseSchedule))], plan["files"][0])
        wizard(service).confirm(ids, plan["revision"], None)
    assert len(list(db.scalars(select(CourseSchedule)))) == 2  # 原有课表 + 新课表
    overlapping = ["OTHER-TC", "OTHER-C", "Other", "1", "1", "2", "1-2", "A101"]
    second = ["OTHER-TC", "OTHER-C", "Other", "1", "2", "3", "1-2", "A102"]
    draft = service.create_preview(service.actor, content=sheet([header, overlapping, second]), **args)
    plan = wizard(service).preview([int(draft.id)])
    assert not plan["can_confirm"]


def test_admin_roster_preview_and_confirm_preserve_class_and_leading_zero(campus):
    from app.modules.academic.models import AdministrativeClass, Student
    from tests.unit.test_campus_configuration import grant
    from tests.unit.test_scoped_importer import sheet
    service, db, own, _, _ = prepare(campus)
    grant(campus[0], campus[2], service.actor, campus[4], ["student.manage"])
    ac = db.get(AdministrativeClass, own.administrative_class_id)
    draft = service.create_preview(service.actor, target="admin_roster", semester_id=None,
        teaching_class_id=None, filename="students.xlsx", replace=False, request_id=None,
        content=sheet([["学号", "姓名", "行政班"], ["00998877", "New student", ac.class_name]]))
    ids = [int(draft.id)]
    plan = wizard(service).preview(ids)
    assert plan["can_confirm"]
    assert db.scalar(select(Student.id).where(Student.student_no == "00998877")) is None
    wizard(service).confirm(ids, plan["revision"], None)
    new = db.scalar(select(Student).where(Student.student_no == "00998877"))
    assert new.administrative_class_id == ac.id
