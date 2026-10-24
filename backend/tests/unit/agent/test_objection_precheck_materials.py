"""使用原FileService鉴权和签名，模拟的仅是对象存储签名边界。"""

from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileObject
from app.modules.objection.models import ObjectionFile
from app.modules.objection.precheck_models import ObjectionPrecheckJob
from app.modules.objection.precheck_service import ObjectionPrecheckService
from sqlalchemy import select
from tests.unit.agent.test_objection_precheck import case_fixture, queue, result


@pytest.fixture(name="case")
def fixture(monkeypatch):
    yield from case_fixture.__wrapped__(monkeypatch)


class SigningStorage:
    def __init__(self):
        self.requests = []

    def presign_get(self, file_id, object_key, ttl_seconds):
        self.requests.append((file_id, ttl_seconds))
        return "https://synthetic.invalid/signed-download?sig=must-not-persist"


def proof(db, objection, uploader, *, key="synthetic-proof", expires=None):
    file = FileObject(
        object_key=key,
        category="OBJECTION_PROOF",
        original_name="证明.png",
        content_type="image/png",
        size_bytes=10,
        sha256="a" * 64,
        uploader_user_id=uploader,
        status="READY",
        expires_at=expires,
    )
    db.add(file)
    db.flush()
    db.add(ObjectionFile(objection_id=objection.id, file_id=file.id))
    db.commit()
    return file


def arrange(case, monkeypatch):
    db, teacher, cid, _, obj, _ = case
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    monkeypatch.setattr(get_settings(), "file_signed_url_ttl_seconds", 900)
    file = proof(db, obj, teacher.id)
    _, job = queue(case)
    storage = SigningStorage()
    svc = ObjectionPrecheckService(db, cid, storage=storage)
    attempt = svc.begin(job.id)
    return svc, job, attempt, file, storage


def test_case_read_returns_only_bound_facts_and_no_storage_paths(case, monkeypatch):
    svc, job, attempt, file, storage = arrange(case, monkeypatch)
    view = svc.case_get(job.id, attempt)
    assert view["objection_id"] == str(job.objection_id)
    assert view["files"][0]["file_id"] == str(file.id)
    assert view["attendance"]["current_version"] == 1
    assert "object_key" not in str(view) and "uploader_user_id" not in str(view)
    assert "authorizer_user_id" not in view and "student_id" not in view
    assert storage.requests == []


def test_material_access_reuses_file_permission_and_caps_link_lifetime(case, monkeypatch):
    db = case[0]
    svc, job, attempt, file, storage = arrange(case, monkeypatch)
    access = svc.file_access(job.id, attempt, file.id)
    assert access.expires_in == 60
    assert storage.requests == [(file.id, 60)]
    assert "must-not-persist" not in str(db.get(ObjectionPrecheckJob, job.id).result_json)
    assert "must-not-persist" not in str([a.after_json for a in db.scalars(select(AuditLog))])


def test_other_objection_file_never_reaches_signer(case, monkeypatch):
    db, teacher, _, _, _, foreign = case
    svc, job, attempt, _, storage = arrange(case, monkeypatch)
    other = proof(db, foreign, teacher.id, key="foreign-proof")
    with pytest.raises(NotFoundError):
        svc.file_access(job.id, attempt, other.id)
    assert storage.requests == []


@pytest.mark.parametrize("mutation", ["reason", "attendance", "file", "closed", "policy"])
def test_current_source_and_authority_rechecked_before_any_material_read(
    case, monkeypatch, mutation
):
    db, teacher, _, _, obj, _ = case
    svc, job, attempt, file, storage = arrange(case, monkeypatch)
    if mutation == "reason":
        obj.reason = "新材料"
    elif mutation == "attendance":
        db.get(AttendanceRecord, obj.attendance_record_id).current_version += 1
    elif mutation == "file":
        file.sha256 = "b" * 64
    elif mutation == "closed":
        obj.final_status = "REJECTED"
    else:
        svc.set_policy(teacher, enabled=False, current_version=1)
    db.commit()
    with pytest.raises((ConflictError, PermissionDeniedError)):
        svc.case_get(job.id, attempt)
    with pytest.raises((ConflictError, PermissionDeniedError)):
        svc.file_access(job.id, attempt, file.id)
    assert storage.requests == []


def test_wrong_attempt_and_completed_run_cannot_read_proof(case, monkeypatch):
    svc, job, attempt, file, storage = arrange(case, monkeypatch)
    with pytest.raises(ConflictError):
        svc.file_access(job.id, "old-attempt", file.id)
    svc.finish(job.id, attempt, result())
    with pytest.raises(ConflictError):
        svc.case_get(job.id, attempt)
    assert storage.requests == []


def test_pending_objection_keeps_existing_expired_proof_access_rule(case, monkeypatch):
    db, teacher, _, _, obj, _ = case
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    file = proof(db, obj, teacher.id, expires=utcnow() - timedelta(days=1))
    svc, job = queue(case)
    svc.storage = SigningStorage()
    access = svc.file_access(job.id, svc.begin(job.id), file.id)
    assert access.expires_in == 60


def test_file_service_denial_is_not_overridden_by_precheck_policy(case, monkeypatch):
    from app.modules.file.service import FileService

    svc, job, attempt, file, storage = arrange(case, monkeypatch)
    monkeypatch.setattr(FileService, "can_access", lambda *args: False)
    with pytest.raises(NotFoundError):
        svc.case_get(job.id, attempt)
    with pytest.raises(NotFoundError):
        svc.file_access(job.id, attempt, file.id)
    assert storage.requests == []


def test_proof_link_cannot_be_echoed_into_saved_advice(case, monkeypatch):
    from app.modules.objection.precheck_schemas import PrecheckResult
    from pydantic import ValidationError

    svc, job, attempt, file, _ = arrange(case, monkeypatch)
    access = svc.file_access(job.id, attempt, file.id)
    with pytest.raises(ValidationError):
        PrecheckResult(recommendation="SUPPORT", summary=access.url, evidence=[])


def test_wrong_file_category_is_not_authorized_by_an_accidental_link(case, monkeypatch):
    db, teacher, _, _, obj, _ = case
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    file = proof(db, obj, teacher.id)
    file.category = "REPORT_FILE"
    db.commit()
    svc, job = queue(case)
    storage = SigningStorage()
    svc.storage = storage
    with pytest.raises(NotFoundError):
        svc.file_access(job.id, svc.begin(job.id), file.id)
    assert storage.requests == []


def test_original_file_access_ttl_is_unchanged_outside_precheck(case, monkeypatch):
    from app.modules.file.service import FileService

    db, teacher, _, _, _, _ = case
    _, _, _, file, storage = arrange(case, monkeypatch)
    access = FileService(db, storage=storage).get_access(teacher, file.id)
    assert access.expires_in == 900 and storage.requests == [(file.id, 900)]


@pytest.mark.parametrize("cap", [0, 301, True])
def test_file_access_rejects_invalid_internal_ttl_limit(case, monkeypatch, cap):
    from app.modules.file.service import FileService

    db, teacher, _, _, _, _ = case
    _, _, _, file, storage = arrange(case, monkeypatch)
    with pytest.raises(ValueError):
        FileService(db, storage=storage).get_access(teacher, file.id, max_ttl_seconds=cap)
    assert storage.requests == []
