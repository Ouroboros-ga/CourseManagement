import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserRole
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from sqlalchemy import delete, select
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result
from tests.unit.test_scoped_objection import service as review_service


@pytest.fixture(name="case")
def fixture(monkeypatch):
    yield from case_fixture.__wrapped__(monkeypatch)


def body(job=None, *, reason=None, version=1):
    return ObjectionFinalReviewRequest(
        decision="REJECTED",
        current_version=version,
        precheck_job_id=str(job.id) if job else None,
        manual_precheck_reason=reason,
    )


def reviewer(case):
    return review_service(case[0], case[1], case[2])


def test_pending_precheck_cannot_be_skipped_even_with_a_manual_reason(case):
    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    svc.begin(job.id)
    with pytest.raises(ConflictError):
        reviewer(case).final_review(teacher, obj.id, body(job, reason="希望直接人工处理"), None)
    assert (
        obj.final_status == "PENDING" and db.get(ObjectionPrecheckJob, job.id).status == "RUNNING"
    )


def test_failed_precheck_requires_seen_job_and_reason_then_audits_manual_fallback(case):
    db, teacher, _, _, obj, _ = case
    _, job = queue(case)
    job.status, job.error_code = "FAILED", "MODEL_FAILED"
    db.commit()
    with pytest.raises(ConflictError):
        reviewer(case).final_review(teacher, obj.id, body(job), None)
    reviewer(case).final_review(teacher, obj.id, body(job, reason="已当面核对原始请假材料"), None)
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "objection.final_review"))
    assert audit.after_json["precheck"]["mode"] == "MANUAL_FALLBACK"
    assert audit.after_json["precheck"]["manual_reason"] == "已当面核对原始请假材料"
    assert obj.final_status == "REJECTED" and job.status == "FAILED"


def test_valid_advice_requires_acknowledging_the_current_record_and_stays_advisory(case):
    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    svc.finish(job.id, svc.begin(job.id), result())
    before = db.get(AttendanceRecord, obj.attendance_record_id).current_version
    with pytest.raises(ConflictError):
        reviewer(case).final_review(teacher, obj.id, body(), None)
    reviewer(case).final_review(teacher, obj.id, body(job), None)
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "objection.final_review"))
    assert audit.after_json["precheck"]["mode"] == "AI_ASSISTED"
    assert audit.after_json["precheck"]["job_id"] == str(job.id)
    assert db.get(AttendanceRecord, obj.attendance_record_id).current_version == before


def test_actual_student_manager_cannot_final_review_with_cached_teacher_label(case):
    db, teacher, _, _, obj, _ = case
    actual = db.scalar(select(Role).where(Role.code == "TEACHER_ADMIN"))
    db.execute(
        delete(UserRole).where(UserRole.user_id == teacher.id, UserRole.role_id == actual.id)
    )
    role = Role(code="STUDENT_AFFAIRS_MANAGER", name="学生负责人")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    db.commit()
    with pytest.raises(PermissionDeniedError):
        reviewer(case).final_review(teacher, obj.id, body(reason="人工核验材料"), None)
    assert obj.final_status == "PENDING"


def test_legacy_case_without_ai_configuration_gets_a_failure_record_before_manual_review(case):
    db, teacher, _, _, obj, _ = case
    reviewer(case).final_review(teacher, obj.id, body(reason="预审服务未接通，已人工核查"), None)
    job = db.scalar(select(ObjectionPrecheckJob))
    assert job is not None and job.status == "FAILED" and job.result_json is None
    assert obj.final_status == "REJECTED"


def test_changed_facts_need_retry_or_recorded_manual_verification(case):
    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    svc.finish(job.id, svc.begin(job.id), result())
    obj.reason = "补交的新说明"
    db.commit()
    with pytest.raises(ConflictError):
        reviewer(case).final_review(teacher, obj.id, body(job), None)
    reviewer(case).final_review(teacher, obj.id, body(job, reason="已核对补交材料的新情况"), None)
    assert obj.final_status == "REJECTED" and job.status == "SUCCEEDED"


def test_failure_of_final_audit_rolls_back_case_and_new_failure_record(case, monkeypatch):
    db, teacher, _, _, obj, _ = case
    service = reviewer(case)

    def fail(**kwargs):
        raise RuntimeError("synthetic final audit failure")

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError):
        service.final_review(teacher, obj.id, body(reason="已人工核查完整材料"), None)
    db.commit()
    db.refresh(obj)
    assert obj.final_status == "PENDING" and db.query(ObjectionPrecheckJob).count() == 0


def test_shared_review_core_does_not_accept_a_missing_prepared_authorization(case):
    db, teacher, _, _, obj, _ = case
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    with pytest.raises(PermissionDeniedError):
        reviewer(case).apply_final_review(
            obj, record, body(reason="人工核查材料"), actor_user_id=teacher.id, request_id=None
        )


def test_prepared_authorization_expires_with_its_transaction(case):
    from app.modules.objection.precheck_review import PreparedFinalReview

    db, teacher, _, _, obj, _ = case
    prepared = PreparedFinalReview.prepare(db, teacher.id, obj.id)
    record = prepared.row[1]
    db.commit()
    with pytest.raises(PermissionDeniedError):
        reviewer(case).apply_final_review(
            obj,
            record,
            body(reason="已人工核查材料"),
            actor_user_id=teacher.id,
            request_id=None,
            precheck_guard=prepared,
        )
    assert obj.final_status == "PENDING" and db.query(ObjectionPrecheckJob).count() == 0


def test_approved_human_decision_keeps_original_attendance_version_and_revision_flow(
    case, monkeypatch
):
    from app.modules.attendance.models import AttendanceRecordVersion
    from app.modules.report.source_revision import SourceRevisionService

    db, teacher, _, _, obj, _ = case
    svc, job = queue(case)
    svc.finish(job.id, svc.begin(job.id), result())
    bumped = []
    monkeypatch.setattr(
        SourceRevisionService, "bump_for_task_id", lambda _, tid: bumped.append(tid)
    )
    reviewer(case).final_review(
        teacher,
        obj.id,
        ObjectionFinalReviewRequest(
            decision="APPROVED",
            final_type="NORMAL",
            current_version=1,
            precheck_job_id=str(job.id),
            comment="已核对请假材料并确认更正",
        ),
        None,
    )
    record = db.get(AttendanceRecord, obj.attendance_record_id)
    assert record.effective_type == "NORMAL" and record.current_version == 2
    assert bumped == [record.task_id]
    version = db.scalar(
        select(AttendanceRecordVersion).where(
            AttendanceRecordVersion.attendance_record_id == record.id,
            AttendanceRecordVersion.version_no == 2,
        )
    )
    assert version.source_type == "OBJECTION_FINAL" and version.changed_by == teacher.id


def test_review_status_exposes_server_side_readiness_for_the_management_ui(case):
    from app.modules.objection.precheck_management import PrecheckManagementService

    db, teacher, cid, _, obj, _ = case
    svc, job = queue(case)
    status = PrecheckManagementService(db, cid)
    svc.begin(job.id)
    view = status.latest(teacher, obj.id)
    assert not view["can_final_review"] and "处理中" in view["review_block_reason"]
    svc.finish(job.id, job.attempt_token, result())
    view = status.latest(teacher, obj.id)
    assert view["can_final_review"] and not view["manual_reason_required"]
    obj.reason = "新事实"
    db.commit()
    view = status.latest(teacher, obj.id)
    assert view["can_final_review"] and view["manual_reason_required"]


def test_http_final_review_requires_server_checked_precheck_ack(case, monkeypatch):
    from tests.unit.agent.test_precheck_management_http import client_for

    db, _, cid, _, obj, _ = case
    svc, job = queue(case)
    svc.finish(job.id, svc.begin(job.id), result())
    client = client_for(case, monkeypatch)
    path = f"/api/v1/colleges/{cid}/objections/{obj.id}/review"
    payload = {"decision": "REJECTED", "current_version": 1}
    assert (
        client.post(path, json={**payload, "precheck_guard": {"prepared": True}}).status_code == 409
    )
    response = client.post(path, json={**payload, "precheck_job_id": str(job.id)})
    assert response.status_code == 200 and response.json()["data"]["final_status"] == "REJECTED"
    db.refresh(obj)
    assert obj.final_status == "REJECTED"


@pytest.mark.parametrize(
    "payload",
    [
        {"precheck_job_id": "9223372036854775808"},
        {"manual_precheck_reason": "   "},
    ],
)
def test_confirmation_fields_reject_overflow_and_blank_reason(payload):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ObjectionFinalReviewRequest(decision="REJECTED", current_version=1, **payload)
