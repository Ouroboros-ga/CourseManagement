"""真实验收缺陷的回归：跨请求持久化和资格底册准备。"""

from io import BytesIO

import openpyxl
import pytest
from app.modules.academic.models import CourseSchedule, TeachingClass
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.report.schemas import AttendanceStatsQuery
from app.modules.report.service import StatisticsService
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_import_confirmation_set import wizard
from tests.unit.test_scoped_academic import records
from tests.unit.test_scoped_file_access import setup
from tests.unit.test_scoped_importer import prepare, preview, sheet


@pytest.fixture(name="campus")
def configured():
    yield from campus_fixture.__wrapped__()


def test_imported_enabled_volunteer_has_passwordless_roster_identity_and_is_idempotent(campus):
    service, db, own, _, semester = prepare(campus)
    for _ in range(2):
        batch = preview(service, semester, own.student_no)
        service.confirm(service.actor, int(batch.id), None)
    db.rollback()
    account = db.scalar(select(UserAccount).where(UserAccount.student_id == own.id))
    assert account is not None, "成功导入资格必须准备排班底册，不能等待微信首次绑定"
    assert account.password_hash is None
    assert set(IdentityRepository(db).list_role_codes(account.id)) == {"STUDENT", "VOLUNTEER"}
    assert (
        db.scalar(
            select(func.count()).select_from(UserAccount).where(UserAccount.student_id == own.id)
        )
        == 1
    )


def test_unchanged_legacy_qualification_reimport_repairs_missing_roster_identity(campus):
    from app.modules.academic.models import VolunteerQualification

    service, db, own, _, semester = prepare(campus)
    db.add(
        VolunteerQualification(
            semester_id=semester,
            student_id=own.id,
            college_id=service.cid,
            enabled=True,
            created_by=service.actor.id,
        )
    )
    db.commit()
    batch = preview(service, semester, own.student_no)
    plan = wizard(service).preview([int(batch.id)])
    wizard(service).confirm([int(batch.id)], plan["revision"], None)
    db.rollback()
    assert db.scalar(select(UserAccount).where(UserAccount.student_id == own.id)) is not None


def test_import_does_not_claim_unrelated_account_with_same_username(campus):
    service, db, own, _, semester = prepare(campus)
    unrelated = UserAccount(username=own.student_no, display_name="Unrelated", status="ACTIVE")
    db.add(unrelated)
    db.commit()
    batch = preview(service, semester, own.student_no)
    plan = wizard(service).preview([int(batch.id)])
    wizard(service).confirm([int(batch.id)], plan["revision"], None)
    account = db.scalar(select(UserAccount).where(UserAccount.student_id == own.id))
    assert account is not None and account.id != unrelated.id
    assert unrelated.student_id is None
    assert IdentityRepository(db).list_role_codes(unrelated.id) == []


def test_self_study_success_survives_request_close_and_repeat_does_not_duplicate(campus):
    _, db, actor, _, a, b = campus
    ac, _, _, teaching, _, _, _ = records(db, a, b)
    class_code = f"SS_EARLY_{ac.class_code}"
    body = dict(
        semester_id=teaching.semester_id,
        study_type="EARLY",
        class_ids=[ac.id],
        weeks=[7],
        weekdays=[2],
        start_period=1,
        end_period=2,
        default_classroom="QA自习室",
    )
    assert (
        ScopedAcademicWriteService(db, actor, int(a["id"])).batch_self_study(body)[
            "schedules_created"
        ]
        == 1
    )
    db.rollback()  # 请求依赖只close；未提交的“成功”不能被下次查询看到。
    with Session(db.get_bind()) as reader:
        saved = reader.scalar(select(TeachingClass).where(TeachingClass.class_code == class_code))
        assert saved is not None, "成功结果须跨请求持久保存"
        assert (
            reader.scalar(
                select(func.count())
                .select_from(CourseSchedule)
                .where(CourseSchedule.teaching_class_id == saved.id)
            )
            == 1
        )
    repeated = ScopedAcademicWriteService(db, actor, int(a["id"])).batch_self_study(body)
    assert repeated["classes_created"] == 0 and repeated["schedules_created"] == 0
    from app.modules.audit.models import AuditLog

    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "academic.course.batch_self_study_create")
    )
    assert audit.after_json["status"] == "ACTIVE", "操作成功状态不能覆盖课程审计状态"


def test_statistics_excel_title_uses_authorized_college(campus, monkeypatch):
    from app.modules.inspection.models import InspectionTask

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    task = db.scalar(
        select(InspectionTask).where(InspectionTask.college_id == int(campus[4]["id"]))
    )
    content, _ = StatisticsService(db, college_id=int(campus[4]["id"])).export_attendance_analytics(
        actor, AttendanceStatsQuery(semester_id=task.semester_id, week_no=task.week_no)
    )
    book = openpyxl.load_workbook(BytesIO(content))
    assert book.worksheets[0]["A1"].value == "甲院 查课考勤多维数据分析看板"


def test_student_import_reports_missing_number_with_source_row(campus):
    service, _, _, _, _ = prepare(campus)
    _, issues, _ = service._parse_admin_roster(
        sheet([["学号", "姓名", "班级"], ["", "测试学生", "测试班"]]), "missing-number.xlsx"
    )
    assert any(i.get("field") == "学号" and i.get("row") == 2 for i in issues)
