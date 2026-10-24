import pytest
from app.modules.agent.import_workspace_worker import ImportWorkspaceWorker
from app.modules.importer.models import ImportBatch
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


@pytest.fixture(name="case")
def fixture(monkeypatch):
    from tests.unit.agent.test_import_workspace import fixture as workspace_fixture

    original = workspace_fixture.__wrapped__(monkeypatch)
    yield next(original)
    with pytest.raises(StopIteration):
        next(original)


def arrange(case):
    from app.modules.academic.models import Student
    from tests.unit.agent.test_import_workspace import arrange as workspace

    service, storage, scope = workspace(case)
    no = case[0][1].scalar(select(Student.student_no).order_by(Student.id).limit(1))
    source = service.upload(
        **scope,
        content=f"学号,是否启用\n{no},是\n".encode(),
        filename="志愿者.csv",
        request_key="volunteers",
    )

    # In-memory DB unit fixture cannot cross processes. Real contained execution has
    # dedicated reopened-file SQLite tests in test_import_preview_process.py.
    def inline_preview(claim, content, **config):
        from app.modules.agent.import_workspace import ImportWorkspaceService

        with sessionmaker(bind=case[0][1].bind)() as db:
            ImportWorkspaceService(db, **config, storage=storage).execute_previews(claim, content)

    worker = ImportWorkspaceWorker(
        sessionmaker(bind=case[0][1].bind),
        case[2].connections,
        environment="dev",
        app_key_id="management",
        storage=storage,
        preview_executor=inline_preview,
    )
    assert worker.run_once()
    return service, worker, scope, int(source["workspace_id"])


def test_prepare_is_durable_and_worker_creates_original_previews_once(case):
    from app.modules.academic.models import VolunteerQualification

    service, worker, scope, wid = arrange(case)
    assert hasattr(service, "prepare_previews"), "Stored preview admission is missing"
    body = {"target": "volunteer", "member_nos": [1], "request_key": "group-one"}
    queued = service.prepare_previews(wid, **scope, **body)
    assert queued["preview"]["status"] == "QUEUED"
    assert case[0][1].query(ImportBatch).count() == 0
    assert worker.run_once()
    ready = service.read(wid, **scope)
    assert ready["preview"]["status"] == "SUCCEEDED"
    ids = ready["preview"]["batch_ids"]
    assert len(ids) == 1
    batch = case[0][1].get(ImportBatch, int(ids[0]))
    assert batch.status == "PREVIEW" and batch.payload_json["agent_workspace_id"] == str(wid)
    assert case[0][1].query(VolunteerQualification).count() == 0
    replay = service.prepare_previews(wid, **scope, **body)
    assert replay["preview"]["batch_ids"] == ids
    assert not worker.run_once() and case[0][1].query(ImportBatch).count() == 1


def test_failed_preview_group_rolls_back_its_original_batches_and_preserves_source(
    case, monkeypatch
):
    from app.modules.importer.service import ImporterService

    service, worker, scope, wid = arrange(case)
    assert hasattr(service, "prepare_previews"), "Stored preview admission is missing"
    service.prepare_previews(wid, **scope, target="volunteer", member_nos=[1], request_key="one")
    original = ImporterService.create_preview

    def fail_after_build(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("synthetic failure before workspace receipt")

    monkeypatch.setattr(ImporterService, "create_preview", fail_after_build)
    assert worker.run_once()
    assert case[0][1].query(ImportBatch).count() == 0
    result = service.read(wid, **scope)
    assert result["state"] == "READY" and result["preview"]["status"] == "FAILED"


def test_recognized_member_cannot_silently_use_another_parser(case):
    from app.core.exceptions import PermissionDeniedError

    service, _, scope, wid = arrange(case)
    with pytest.raises(PermissionDeniedError):
        service.prepare_previews(
            wid, **scope, target="admin_roster", member_nos=[1], request_key="wrong"
        )
    assert service.read(wid, **scope)["state"] == "READY"


def test_cancel_fences_preview_claim_and_records_terminal_receipt(case):
    service, _, scope, wid = arrange(case)
    service.prepare_previews(wid, **scope, target="volunteer", member_nos=[1], request_key="cancel")
    claim = service.claim()
    assert claim.stage == "PREVIEW"
    service.cancel(wid, **scope)
    canceled = service.read(wid, **scope)
    assert canceled["preview"]["status"] == "CANCELED"
    assert service.execute_previews(claim, b"unused") is False
    assert case[0][1].query(ImportBatch).count() == 0


def test_failed_later_group_preserves_earlier_preview_and_idempotency(case, monkeypatch):
    from app.core.exceptions import ConflictError
    from app.modules.importer.service import ImporterService

    service, worker, scope, wid = arrange(case)
    first = dict(target="volunteer", member_nos=[1], request_key="first")
    service.prepare_previews(wid, **scope, **first)
    worker.run_once()
    ids = service.read(wid, **scope)["preview"]["batch_ids"]
    service.prepare_previews(wid, **scope, target="volunteer", member_nos=[1], request_key="second")
    monkeypatch.setattr(
        ImporterService,
        "create_preview",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("failure")),
    )
    worker.run_once()
    assert service.read(wid, **scope)["preview"]["status"] == "FAILED"
    assert service.prepare_previews(wid, **scope, **first)["preview"]["batch_ids"] == ids
    assert case[0][1].query(ImportBatch).count() == 1
    with pytest.raises(ConflictError):
        service.prepare_previews(wid, **scope, **{**first, "course_type_id": "1"})


def test_preview_crash_budget_records_terminal_receipt(case):
    from datetime import timedelta

    from app.core.database import utcnow
    from app.modules.agent.import_workspace_models import AgentImportWorkspace

    service, _, scope, wid = arrange(case)
    service.prepare_previews(wid, **scope, target="volunteer", member_nos=[1], request_key="crash")
    for _ in range(3):
        assert service.claim().stage == "PREVIEW"
        row = case[0][1].get(AgentImportWorkspace, wid)
        row.lease_until = utcnow() - timedelta(seconds=1)
        case[0][1].commit()
    assert service.claim() is None
    assert service.read(wid, **scope)["preview"]["status"] == "FAILED"


def test_cancel_during_parsing_discards_drafts_at_final_claim_check(case, monkeypatch):
    from contextlib import contextmanager

    from app.modules.importer.scoped_service import ScopedImporterService

    service, worker, scope, wid = arrange(case)
    service.prepare_previews(
        wid, **scope, target="volunteer", member_nos=[1], request_key="cancel-during"
    )
    original = ScopedImporterService.draft_source_snapshot

    @contextmanager
    def cancel_before_parsing(importer):
        service.cancel(wid, **scope)
        with original(importer):
            yield

    monkeypatch.setattr(ScopedImporterService, "draft_source_snapshot", cancel_before_parsing)
    assert worker.run_once()
    assert service.read(wid, **scope)["state"] == "CANCELED"
    assert case[0][1].query(ImportBatch).count() == 0
