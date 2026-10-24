import importlib.util
from datetime import timedelta

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.modules.agent.models import AgentRun
from sqlalchemy.orm import sessionmaker


class Storage:
    def __init__(self):
        self.objects = {}

    def save(self, key, data, content_type):
        self.objects[key] = data

    def read(self, key):
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(key, None)


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_conversations import fixture as conversation_fixture

    original = conversation_fixture.__wrapped__(monkeypatch)
    value = next(original)
    monkeypatch.setattr(get_settings(), "agent_tools_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_import_workspace_enabled", True)
    yield value
    with pytest.raises(StopIteration):
        next(original)


def arrange(case):
    assert importlib.util.find_spec("app.modules.agent.import_workspace") is not None, (
        "Persistent import workspace is missing"
    )
    from app.modules.agent.import_workspace import ImportWorkspaceService

    db = case[0][1]
    run = db.query(AgentRun).one()
    storage = Storage()
    service = ImportWorkspaceService(
        db, case[2].connections, environment="dev", app_key_id="management", storage=storage
    )
    scope = {
        "user_id": case[1].id,
        "session_id": run.source_session_id,
        "college_id": run.college_id,
        "semester_id": run.semester_id,
    }
    return service, storage, scope


def upload(service, scope, **extra):
    return service.upload(
        **scope,
        content="工号,姓名\n00123,合成教师\n".encode(),
        filename="教师.csv",
        request_key="source-one",
        **extra,
    )


def test_original_blob_and_queue_receipt_survive_without_formal_import_or_tokens(case):
    from app.modules.file.models import FileObject
    from app.modules.importer.models import ImportBatch

    service, storage, scope = arrange(case)
    before = case[0][1].query(FileObject).count()
    result = upload(service, scope)
    assert result["state"] == "QUEUED" and result["inspection"] is None
    assert len(storage.objects) == 1
    assert case[0][1].query(FileObject).count() == before + 1
    assert case[0][1].query(ImportBatch).count() == 0
    assert not any(key in str(result) for key in ["object_key", "run_token", "file_id", "run_id"])
    assert upload(service, scope)["workspace_id"] == result["workspace_id"]
    assert len(storage.objects) == 1


def test_changed_upload_key_conflicts_and_wrong_context_cannot_read(case):
    service, storage, scope = arrange(case)
    result = upload(service, scope)
    with pytest.raises(AppError) as error:
        service.upload(**scope, content=b"changed", filename="教师.csv", request_key="SOURCE-ONE")
    assert error.value.http_status == 409 and len(storage.objects) == 1
    for wrong in [
        {"user_id": scope["user_id"] + 100},
        {"session_id": scope["session_id"] + 100},
        {"college_id": scope["college_id"] + 100},
        {"semester_id": scope["semester_id"] + 100},
    ]:
        with pytest.raises(AppError):
            service.read(int(result["workspace_id"]), **{**scope, **wrong})


def test_real_inspection_worker_reads_original_blob_and_saves_only_metadata(case):
    from app.modules.agent.import_workspace_worker import ImportWorkspaceWorker

    service, storage, scope = arrange(case)
    result = upload(service, scope)
    worker = ImportWorkspaceWorker(
        sessionmaker(bind=case[0][1].bind),
        case[2].connections,
        environment="dev",
        app_key_id="management",
        storage=storage,
    )
    assert worker.run_once()
    ready = service.read(int(result["workspace_id"]), **scope)
    assert ready["state"] == "READY"
    assert ready["inspection"]["files"][0]["target"] == "faculty_staff"
    assert ready["business_data_applied"] is False
    assert not worker.run_once()


def test_revocation_after_upload_prevents_inspection(case):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding

    service, storage, scope = arrange(case)
    upload(service, scope)
    for binding in case[0][1].query(TeacherCollegeBinding).all():
        case[0][1].delete(binding)
    case[0][1].commit()
    claim = service.claim()
    assert claim is None or not claim.can_inspect
    with pytest.raises(AppError):
        service.read(1, **scope)


def test_cancel_or_expired_lease_rejects_late_inspection(case):
    from app.modules.agent.import_workspace_models import AgentImportWorkspace

    service, storage, scope = arrange(case)
    result = upload(service, scope)
    claim = service.claim()
    assert claim.can_inspect and not case[0][1].in_transaction()
    row = case[0][1].get(AgentImportWorkspace, int(result["workspace_id"]))
    row.lease_until = utcnow() - timedelta(seconds=1)
    case[0][1].commit()
    assert not service.finish(claim, None, error_code="TEST_FAILURE")
    service.cancel(int(result["workspace_id"]), **scope)
    assert service.read(int(result["workspace_id"]), **scope)["state"] == "CANCELED"
    assert service.claim() is None


def test_raw_original_is_not_exposed_through_generic_file_access(case):
    from app.modules.file.models import FileObject
    from app.modules.file.service import FileService

    service, storage, scope = arrange(case)
    upload(service, scope)
    original = case[0][1].query(FileObject).filter_by(category="IMPORT_FILE").one()
    assert FileService(case[0][1], storage=storage).can_access(case[1], original) is False


def test_untrusted_inspector_result_becomes_failed_without_killing_the_consumer(case):
    from app.modules.agent.import_workspace_worker import ImportWorkspaceWorker

    service, storage, scope = arrange(case)
    result = upload(service, scope)
    worker = ImportWorkspaceWorker(
        sessionmaker(bind=case[0][1].bind),
        case[2].connections,
        environment="dev",
        app_key_id="management",
        storage=storage,
        inspector=lambda *args: {"business_data_applied": True, "run_token": "untrusted"},
    )
    assert worker.run_once()
    failed = service.read(int(result["workspace_id"]), **scope)
    assert failed["state"] == "FAILED" and failed["inspection"] is None


def test_metadata_change_after_claim_cannot_publish_a_stale_manifest(case):
    from app.modules.agent.import_workspace_models import AgentImportWorkspace
    from app.modules.file.models import FileObject

    service, storage, scope = arrange(case)
    result = upload(service, scope)
    claim = service.claim()
    row = case[0][1].get(AgentImportWorkspace, int(result["workspace_id"]))
    original = case[0][1].get(FileObject, row.file_id)
    original.sha256 = "f" * 64
    case[0][1].commit()
    inspection = {
        "protocol_version": 1,
        "source_sha256": claim.sha256,
        "business_data_applied": False,
        "files": [
            {
                "member_no": 1,
                "filename": claim.filename,
                "archive_member": None,
                "target": "faculty_staff",
                "blocked": False,
                "message": "",
                "sha256": claim.sha256,
                "size_bytes": claim.size_bytes,
                "duplicate_of": None,
            }
        ],
    }
    service.finish(claim, inspection)
    case[0][1].refresh(row)
    assert row.state == "FAILED" and row.inspection_json is None


def test_revocation_during_storage_io_does_not_leave_a_source_or_file_row(case):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding
    from app.modules.agent.import_workspace_models import AgentImportWorkspace
    from app.modules.file.models import FileObject

    service, storage, scope = arrange(case)
    before = case[0][1].query(FileObject).count()
    save = storage.save

    def revoke(key, content, mime):
        assert not case[0][1].in_transaction()
        save(key, content, mime)
        for row in case[0][1].query(TeacherCollegeBinding).all():
            case[0][1].delete(row)
        case[0][1].commit()

    storage.save = revoke
    with pytest.raises(AppError):
        upload(service, scope)
    assert not storage.objects
    assert case[0][1].query(AgentImportWorkspace).count() == 0
    assert case[0][1].query(FileObject).count() == before


def test_lease_reclaim_fences_old_receipt_and_stops_after_three_attempts(case):
    from app.modules.agent.import_workspace_models import AgentImportWorkspace

    service, _, scope = arrange(case)
    result = upload(service, scope)
    first = service.claim()
    for count in (1, 2, 3):
        row = case[0][1].get(AgentImportWorkspace, int(result["workspace_id"]))
        assert row.attempt_count == count
        row.lease_until = utcnow() - timedelta(seconds=1)
        case[0][1].commit()
        claim = service.claim()
        assert not service.finish(first, None, error_code="old_receipt")
        if count < 3:
            assert claim and claim.attempt_token != first.attempt_token
        else:
            assert claim is None
    case[0][1].refresh(row)
    assert row.state == "FAILED" and row.attempt_count == 3
    assert row.error_code == "IMPORT_INSPECTION_FAILED"


def test_expiring_orm_does_not_reopen_a_transaction_when_claim_leaves(case):
    service, _, scope = arrange(case)
    upload(service, scope)
    db = case[0][1]
    db.expire_on_commit = True
    try:
        claim = service.claim()
        assert claim.can_inspect and claim.filename and not db.in_transaction()
    finally:
        db.expire_on_commit = False


def test_source_bytes_changed_in_storage_fail_before_parser(case):
    from app.modules.agent.import_workspace_worker import ImportWorkspaceWorker

    service, storage, scope = arrange(case)
    result = upload(service, scope)
    key = next(iter(storage.objects))
    storage.objects[key] = b"changed source bytes"
    worker = ImportWorkspaceWorker(
        sessionmaker(bind=case[0][1].bind),
        case[2].connections,
        environment="dev",
        app_key_id="management",
        storage=storage,
        inspector=lambda *args: pytest.fail("changed source must not be parsed"),
    )
    assert worker.run_once()
    failed = service.read(int(result["workspace_id"]), **scope)
    assert failed["state"] == "FAILED" and failed["error_code"] == "SOURCE_CHANGED"


def test_reopened_sqlite_database_and_local_storage_resume_a_queued_source(case, tmp_path):
    import sqlite3

    from app.modules.agent.import_workspace import ImportWorkspaceService
    from app.modules.agent.import_workspace_worker import ImportWorkspaceWorker
    from app.modules.file.storage import LocalStorage
    from sqlalchemy import create_engine

    service, _, scope = arrange(case)
    service.storage = LocalStorage(str(tmp_path / "files"), "s" * 32)
    result = upload(service, scope)
    path = tmp_path / "reopened.db"
    original = case[0][1].bind.raw_connection()
    try:
        with sqlite3.connect(path) as target:
            original.driver_connection.backup(target)
    finally:
        original.close()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    factory = sessionmaker(bind=engine)
    storage = LocalStorage(str(tmp_path / "files"), "s" * 32)
    try:
        worker = ImportWorkspaceWorker(
            factory,
            case[2].connections,
            environment="dev",
            app_key_id="management",
            storage=storage,
        )
        assert worker.run_once()
        with factory() as db:
            reopened = ImportWorkspaceService(
                db, case[2].connections, environment="dev", app_key_id="management", storage=storage
            )
            assert reopened.read(int(result["workspace_id"]), **scope)["state"] == "READY"
    finally:
        engine.dispose()


def test_user_source_quota_cannot_be_bypassed_by_canceling_or_replaying(case):
    service, storage, scope = arrange(case)
    for index in range(20):
        row = service.upload(
            **scope, content=b"unknown\nvalue", filename="one.csv", request_key=f"one-{index}"
        )
        service.cancel(int(row["workspace_id"]), **scope)
    with pytest.raises(AppError) as error:
        service.upload(
            **scope, content=b"unknown\nvalue", filename="one.csv", request_key="twenty-one"
        )
    assert error.value.http_status == 429 and len(storage.objects) == 20
    assert (
        service.upload(**scope, content=b"unknown\nvalue", filename="one.csv", request_key="ONE-0")[
            "state"
        ]
        == "CANCELED"
    )
