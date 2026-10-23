"""DEC-01：志愿者提交后两小时内的本人纠错闭环（修改并重新提交 / 撤回）。

窗口起点是任务首次成功提交时刻，改版与撤回都不重置；原始 attempt 永久保留为历史，
考勤由新 attempt 就地改写并追加版本，撤回则让考勤退出有效结论而同样保留版本链。
已有管理员更正或异议终审结论时本人不得覆盖。
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.modules.academic.models import Student, VolunteerQualification
from app.modules.attendance.effect_scope import see_withdrawn
from app.modules.attendance.models import (
    AttendanceEffectState,
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
)
from app.modules.attendance.repository import AttendanceRepository
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
from app.modules.inspection.repository import InspectionRepository
from app.modules.inspection.schemas import (
    SubmissionAbnormalItemInput,
    SubmissionCreateRequest,
    SubmissionWithdrawRequest,
)
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


def _states(db, task_id):
    return {
        row.student_id: row.effect_state
        for row in db.scalars(
            see_withdrawn(select(AttendanceRecord).where(AttendanceRecord.task_id == task_id))
        )
    }


def _versions(db, record_id):
    return list(
        db.scalars(
            select(AttendanceRecordVersion)
            .where(AttendanceRecordVersion.attendance_record_id == record_id)
            .order_by(AttendanceRecordVersion.version_no)
        )
    )


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


# ============================ 撤回 ============================ #


def test_withdraw_retires_attendance_but_keeps_every_fact(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch, result="ABNORMAL")
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.task_id == task.id))

    result = service.withdraw_submission(
        actor, int(first.id), SubmissionWithdrawRequest(reason="照片拍错了班级"), None
    )

    assert result.submission_state == SubmissionState.WITHDRAWN.value
    assert result.withdraw_reason == "照片拍错了班级"
    assert result.withdrawn_at is not None
    assert result.can_correct is False

    stored = db.get(InspectionSubmission, int(first.id))
    # 有效性走 submission_state，review_status 轴不动，避免既有"曾形成正式结论"判断失真。
    assert stored.review_status == ReviewStatus.APPROVED.value
    assert len(stored.abnormal_items) == 1  # 原始明细保留可读

    assert _types(db, task.id) == {}  # 默认读取已取不到结论
    assert _states(db, task.id) == {own.id: AttendanceEffectState.WITHDRAWN.value}

    versions = _versions(db, record.id)
    assert [v.source_type for v in versions] == [
        AttendanceSourceType.SUBMISSION.value,
        AttendanceSourceType.WITHDRAWAL.value,
    ]
    assert [v.version_no for v in versions] == [1, 2]
    assert versions[1].attendance_type == "ABSENT"  # 记录退出有效时的那份认定
    assert versions[1].changed_by == actor.id


def test_withdrawn_attendance_is_invisible_to_management_read_paths(campus, monkeypatch):
    db, service, actor, task, first, _own = _submitted(campus, monkeypatch)
    record_id = db.scalar(
        see_withdrawn(select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id))
    )
    service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)

    assert AttendanceRepository(db).get_record(record_id) is None
    assert AttendanceRepository(db).get_record_for_update(record_id) is None
    assert db.get(AttendanceRecord, record_id) is None


def test_withdraw_reopens_task_without_a_conclusion(campus, monkeypatch):
    """撤回后任务回到"尚无有效结论"：五态推导与取消闸门都据此打开。"""
    db, service, actor, task, first, _own = _submitted(campus, monkeypatch)
    repo = InspectionRepository(db)

    def flags():
        # 与 _assemble_tasks 一致：无有效提交的行不在聚合结果里，缺省即 (False, False)。
        return repo.map_submission_flags_by_task_ids([task.id]).get(task.id, (False, False))

    assert flags() == (True, False)
    assert repo.has_approved_submission(task.id) is True
    service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    assert flags() == (False, False)
    assert repo.has_approved_submission(task.id) is False


def test_resubmit_after_withdraw_restores_the_same_conclusion(campus, monkeypatch):
    """撤回后重新提交同一结论：认定值没变，但考勤行必须回到有效，否则任务静默失去结论。"""
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    record_id = db.scalar(
        see_withdrawn(select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id))
    )
    service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)

    again = service.create_submission(
        actor, task.id, SubmissionCreateRequest(result="NORMAL"), None
    )

    assert again.attempt_no == 2
    assert again.submission_state == SubmissionState.ACTIVE.value
    assert _types(db, task.id) == {own.id: "NORMAL"}
    assert [v.source_type for v in _versions(db, record_id)] == [
        AttendanceSourceType.SUBMISSION.value,
        AttendanceSourceType.WITHDRAWAL.value,
        AttendanceSourceType.SUBMISSION.value,
    ]


def test_withdraw_after_window_closes_is_rejected(campus, monkeypatch):
    db, service, actor, _task, first, _own = _submitted(campus, monkeypatch)
    stored = db.get(InspectionSubmission, int(first.id))
    monkeypatch.setattr(
        "app.modules.inspection.service.utcnow",
        lambda: stored.submitted_at
        + timedelta(minutes=get_settings().submission_correction_window_minutes),
    )
    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    assert stored.submission_state == SubmissionState.ACTIVE.value


def test_withdraw_cannot_overwrite_admin_correction(campus, monkeypatch):
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
        service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    db.rollback()
    assert _types(db, task.id) == {own.id: "LEAVE"}
    assert db.get(InspectionSubmission, int(first.id)).submission_state == (
        SubmissionState.ACTIVE.value
    )


def test_second_withdraw_is_rejected_and_adds_no_version(campus, monkeypatch):
    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    record_id = db.scalar(
        see_withdrawn(select(AttendanceRecord.id).where(AttendanceRecord.task_id == task.id))
    )
    service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    before = len(_versions(db, record_id))

    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError):
        service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    assert len(_versions(db, record_id)) == before
    assert _states(db, task.id) == {own.id: AttendanceEffectState.WITHDRAWN.value}


def test_other_volunteers_submission_cannot_be_withdrawn(campus, monkeypatch):
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
        service.withdraw_submission(outsider, int(first.id), SubmissionWithdrawRequest(), None)


def test_failed_revise_keeps_old_submission_and_attendance_active(campus, monkeypatch):
    from app.core.exceptions import AppError

    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    with pytest.raises(AppError):
        service.revise_submission(
            actor, int(first.id), SubmissionCreateRequest(result="NORMAL", file_ids=[999999]), None
        )
    # Even an internal caller's later commit cannot persist half of the revision.
    db.commit()
    db.expire_all()
    original = db.get(InspectionSubmission, int(first.id))
    assert original.submission_state == "ACTIVE"
    assert original.superseded_by_submission_id is None
    assert service._repo.has_open_submission(task.id)
    assert _types(db, task.id) == {own.id: "NORMAL"}


@pytest.mark.parametrize("closed_by", ["elapsed", "disabled"])
def test_withdrawn_task_cannot_be_resubmitted_after_window_closes(campus, monkeypatch, closed_by):
    from app.core.exceptions import ConflictError

    db, service, actor, task, first, own = _submitted(campus, monkeypatch)
    service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
    if closed_by == "elapsed":
        monkeypatch.setattr(
            "app.modules.inspection.service.utcnow",
            lambda: first.submitted_at + timedelta(hours=2),
        )
    else:
        monkeypatch.setattr(get_settings(), "submission_correction_window_minutes", 0)
    with pytest.raises(ConflictError):
        service.create_submission(actor, task.id, SubmissionCreateRequest(result="NORMAL"), None)
    db.commit()
    assert _types(db, task.id) == {}
    assert _states(db, task.id) == {own.id: "WITHDRAWN"}


@pytest.mark.parametrize("decision", ["REJECTED", "APPROVED"])
@pytest.mark.parametrize("operation", ["withdraw", "revise"])
def test_closed_objection_without_type_change_protects_conclusion(
    campus, monkeypatch, decision, operation
):
    from app.core.exceptions import ConflictError
    from app.modules.objection.models import Objection
    from app.modules.objection.schemas import ObjectionFinalReviewRequest
    from app.modules.objection.service import ObjectionService

    db, service, actor, task, first, own = _submitted(campus, monkeypatch, result="ABNORMAL")
    record = db.scalar(select(AttendanceRecord).where(AttendanceRecord.task_id == task.id))
    objection = Objection(
        attendance_record_id=record.id, student_id=own.id,
        base_attendance_version=record.current_version, reason="申请复核", desired_type="NORMAL",
    )
    db.add(objection)
    db.flush()
    ObjectionService(db).apply_final_review(
        objection, record,
        ObjectionFinalReviewRequest(
            decision=decision, current_version=record.current_version,
            final_type="ABSENT" if decision == "APPROVED" else None,
        ),
        actor_user_id=campus[2].id, request_id=None,
    )
    db.commit()
    with pytest.raises(ConflictError):
        if operation == "withdraw":
            service.withdraw_submission(actor, int(first.id), SubmissionWithdrawRequest(), None)
        else:
            service.revise_submission(
                actor, int(first.id), SubmissionCreateRequest(result="NORMAL"), None
            )
    db.rollback()
    assert _types(db, task.id) == {own.id: "ABSENT"}
    assert db.get(InspectionSubmission, int(first.id)).submission_state == "ACTIVE"
