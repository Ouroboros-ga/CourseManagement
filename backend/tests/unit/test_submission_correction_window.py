"""DEC-01：志愿者提交后两小时内的本人纠错闭环（修改并重新提交）。

窗口起点是任务首次成功提交时刻，改版不重置；原始 attempt 永久保留为历史，
考勤由新 attempt 就地改写并追加版本。已有管理员更正或异议终审结论时本人不得覆盖。
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.modules.academic.models import Student, VolunteerQualification
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
)
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import (
    InspectionAssignment,
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    SubmissionState,
)
from app.modules.inspection.schemas import SubmissionAbnormalItemInput, SubmissionCreateRequest
from app.modules.inspection.service import InspectionService
from app.modules.report.source_revision import SourceRevisionService
from app.modules.volunteer.member_service import GroupMemberService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def _submitted(campus, monkeypatch, *, result="NORMAL"):
    """建立"志愿者已对本人受派任务成功提交一次"的起始状态。"""
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    sync_registry(db)
    foreign = db.scalar(select(Student).where(Student.student_no == "B"))
    volunteer = UserAccount(display_name="志愿者", student_id=foreign.id, status="ACTIVE")
    db.add(volunteer)
    db.flush()
    for code in ("STUDENT", "VOLUNTEER"):
        db.add(
            UserRole(
                user_id=volunteer.id, role_id=db.scalar(select(Role.id).where(Role.code == code))
            )
        )
    db.add(
        VolunteerQualification(
            student_id=foreign.id, semester_id=sem.id, college_id=int(campus[5]["id"]),
            enabled=True,
        )
    )
    db.commit()
    members = GroupMemberService(db, admin, int(a["id"]), int(group["id"]))
    body = {
        "student_id": str(foreign.id),
        "semester_id": str(sem.id),
        "effective_from": "2026-09-01",
        "effective_to": "2027-01-30",
    }
    members.authorize_support(body)
    members.create(body)
    sampling = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    request = {
        "semester_id": str(sem.id),
        "date_from": "2026-09-07",
        "date_to": "2026-09-07",
        "counts": {str(own.administrative_class_id): 1},
        "draw_id": "correction-window",
        "require_photo": False,
    }
    generated = sampling.generate(request, sampling.preview(request)["selection_revision"])
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    db.add(
        InspectionAssignment(
            task_id=task.id,
            volunteer_user_id=volunteer.id,
            assign_method="MANUAL",
            assigned_by=admin.id,
        )
    )
    db.commit()
    if db.get_bind().dialect.name != "mysql":
        # SQLite 不验证 MySQL UPSERT；真实源修订写入由 MySQL 集成用例覆盖。
        monkeypatch.setattr(SourceRevisionService, "bump_for_task", lambda *_: None)
    actor = replace(
        admin, id=volunteer.id, roles=["STUDENT", "VOLUNTEER"], permissions=["submission.create"]
    )
    service = InspectionService(db)
    abnormal = (
        [SubmissionAbnormalItemInput(student_id=own.id, attendance_type="ABSENT")]
        if result == "ABNORMAL"
        else []
    )
    first = service.create_submission(
        actor, task.id, SubmissionCreateRequest(result=result, abnormal_items=abnormal), None
    )
    return db, service, actor, task, first, own


def _types(db, task_id):
    return {
        row.student_id: row.effective_type
        for row in db.scalars(select(AttendanceRecord).where(AttendanceRecord.task_id == task_id))
    }


def test_first_submission_is_active_and_exposes_correction_deadline(campus, monkeypatch):
    db, _service, _actor, task, first, _own = _submitted(campus, monkeypatch)
    stored = db.get(InspectionSubmission, int(first.id))
    assert stored.submission_state == SubmissionState.ACTIVE.value
    assert stored.review_status == ReviewStatus.APPROVED.value
    window = get_settings().submission_correction_window_minutes
    assert first.correction_deadline_at == stored.submitted_at + timedelta(minutes=window)
    assert first.can_correct is True


def test_revise_supersedes_history_and_rewrites_attendance(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    original_deadline = first.correction_deadline_at
    original_submitted_at = db.get(InspectionSubmission, int(first.id)).submitted_at

    revised = service.revise_submission(
        actor,
        int(first.id),
        SubmissionCreateRequest(
            result="ABNORMAL",
            abnormal_items=[
                SubmissionAbnormalItemInput(student_id=own.id, attendance_type="ABSENT")
            ],
            note="漏报一名缺勤",
        ),
        None,
    )

    assert revised.attempt_no == int(first.attempt_no) + 1
    assert revised.submission_state == SubmissionState.ACTIVE.value
    # 窗口不因改版重置：截止时刻与首次提交时间都保持原值。
    assert revised.correction_deadline_at == original_deadline
    assert revised.submitted_at >= original_submitted_at

    old = db.get(InspectionSubmission, int(first.id))
    assert old.submission_state == SubmissionState.SUPERSEDED.value
    assert old.superseded_by_submission_id == int(revised.id)
    assert old.submitted_at == original_submitted_at
    assert old.abnormal_items == []  # 旧 attempt 的明细原样保留，未被新提交改写

    # 当前有效考勤反映新结论，并追加 SUBMISSION 版本，不删除历史版本。
    assert _types(db, task.id)[own.id] == "ABSENT"
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.task_id == task.id))
    versions = list(
        db.scalars(
            select(AttendanceRecordVersion).where(
                AttendanceRecordVersion.attendance_record_id == record.id
            ).order_by(AttendanceRecordVersion.version_no)
        )
    )
    assert [v.version_no for v in versions] == [1, 2]
    assert [v.source_type for v in versions] == [
        AttendanceSourceType.SUBMISSION.value,
        AttendanceSourceType.SUBMISSION.value,
    ]
    assert versions[0].attendance_type == "NORMAL"
    assert versions[1].attendance_type == "ABSENT"


def test_revise_after_window_closes_is_rejected(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    stored = db.get(InspectionSubmission, int(first.id))
    monkeypatch.setattr(
        "app.modules.inspection.service.utcnow",
        lambda: stored.submitted_at
        + timedelta(minutes=get_settings().submission_correction_window_minutes),
    )
    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.revise_submission(
            actor, int(first.id), SubmissionCreateRequest(result="NORMAL"), None
        )
    assert stored.submission_state == SubmissionState.ACTIVE.value


def test_window_closes_immediately_when_configured_zero(campus, monkeypatch):
    monkeypatch.setattr(get_settings(), "submission_correction_window_minutes", 0)
    db, service, actor, _task, first, _own = _submitted(campus, monkeypatch)
    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.revise_submission(
            actor, int(first.id), SubmissionCreateRequest(result="NORMAL"), None
        )


def test_revise_cannot_overwrite_admin_correction(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.task_id == task.id))
    record.effective_type = "LEAVE"
    db.add(
        AttendanceRecordVersion(
            attendance_record_id=record.id,
            version_no=record.current_version + 1,
            attendance_type="LEAVE",
            source_type=AttendanceSourceType.CORRECTION.value,
            source_id=record.id,
            changed_by=1,
            reason="管理员独立更正",
        )
    )
    record.current_version += 1
    db.commit()

    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.revise_submission(
            actor,
            int(first.id),
            SubmissionCreateRequest(
                result="ABNORMAL",
                abnormal_items=[
                    SubmissionAbnormalItemInput(student_id=own.id, attendance_type="ABSENT")
                ],
            ),
            None,
        )
    db.rollback()
    assert record.effective_type == "LEAVE"
    assert db.get(InspectionSubmission, int(first.id)).submission_state == (
        SubmissionState.ACTIVE.value
    )


def test_other_volunteers_submission_id_is_not_revealed(campus, monkeypatch):
    db, service, _actor, _task, first, _own = _submitted(campus, monkeypatch)
    stranger = UserAccount(display_name="旁人", status="ACTIVE")
    db.add(stranger)
    db.flush()
    db.add(
        UserRole(
            user_id=stranger.id,
            role_id=db.scalar(select(Role.id).where(Role.code == "VOLUNTEER")),
        )
    )
    db.commit()
    outsider = CurrentUser(
        stranger.id, "stranger", "旁人", "ACTIVE", ["VOLUNTEER"], ["submission.create"]
    )
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        service.revise_submission(
            outsider, int(first.id), SubmissionCreateRequest(result="NORMAL"), None
        )


def test_second_revise_uses_new_active_submission(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    second = service.revise_submission(
        actor,
        int(first.id),
        SubmissionCreateRequest(
            result="ABNORMAL",
            abnormal_items=[
                SubmissionAbnormalItemInput(student_id=own.id, attendance_type="LATE")
            ],
        ),
        None,
    )
    third = service.revise_submission(
        actor,
        int(second.id),
        SubmissionCreateRequest(
            result="ABNORMAL",
            abnormal_items=[
                SubmissionAbnormalItemInput(student_id=own.id, attendance_type="LEAVE")
            ],
        ),
        None,
    )
    assert third.attempt_no == 3
    assert _types(db, task.id)[own.id] == "LEAVE"
    states = {
        row.attempt_no: row.submission_state
        for row in db.scalars(
            select(InspectionSubmission).where(InspectionSubmission.task_id == task.id)
        )
    }
    assert states == {1: "SUPERSEDED", 2: "SUPERSEDED", 3: "ACTIVE"}

    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.revise_submission(
            actor, int(first.id), SubmissionCreateRequest(result="NORMAL"), None
        )
