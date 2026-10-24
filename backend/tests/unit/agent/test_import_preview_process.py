import importlib
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.unit.agent.test_import_workspace_previews import arrange, fixture  # noqa: F401


def durable_claim(case, tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.modules.agent.import_workspace import ImportWorkspaceService

    service, worker, scope, wid = arrange(case)
    service.prepare_previews(
        wid, **scope, target="volunteer", member_nos=[1], request_key="bounded"
    )
    claim = service.claim()
    content = worker.storage.read(claim.object_key)
    path = tmp_path / "preview.db"
    raw = case[0][1].bind.raw_connection()
    try:
        with sqlite3.connect(path) as target:
            raw.driver_connection.backup(target)
    finally:
        raw.close()
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite:///{path.as_posix()}")
    engine = create_engine(get_settings().database_url)
    factory = sessionmaker(bind=engine)
    return claim, content, scope, factory, engine, ImportWorkspaceService


def test_real_bounded_preview_child_commits_original_batches_with_receipt(
    case, tmp_path, monkeypatch
):
    from app.modules.importer.models import ImportBatch

    module = importlib.import_module("app.modules.agent.import_preview_process")
    claim, content, scope, factory, engine, service_type = durable_claim(
        case, tmp_path, monkeypatch
    )
    try:
        module.run_preview_claim(
            claim,
            content,
            environment="dev",
            app_key_id="management",
            connections=case[2].connections,
        )
        with factory() as db:
            service = service_type(
                db, case[2].connections, environment="dev", app_key_id="management"
            )
            result = service.read(claim.workspace_id, **scope)
            assert result["preview"]["status"] == "SUCCEEDED"
            assert db.query(ImportBatch).count() == 1
    finally:
        engine.dispose()


def test_preview_child_timeout_is_killed_without_partial_drafts(case, tmp_path, monkeypatch):
    from app.modules.agent.import_inspection import InspectionError
    from app.modules.importer.models import ImportBatch

    module = importlib.import_module("app.modules.agent.import_preview_process")
    claim, content, scope, factory, engine, service_type = durable_claim(
        case, tmp_path, monkeypatch
    )
    try:
        with pytest.raises(InspectionError, match="IMPORT_PREVIEW_TIMEOUT"):
            module.run_preview_claim(
                claim,
                content,
                environment="dev",
                app_key_id="management",
                connections=case[2].connections,
                timeout_seconds=0.001,
            )
        with factory() as db:
            service = service_type(
                db, case[2].connections, environment="dev", app_key_id="management"
            )
            assert service.finish(claim, None, error_code="IMPORT_PREVIEW_TIMEOUT")
            assert db.query(ImportBatch).count() == 0
            assert service.read(claim.workspace_id, **scope)["preview"]["status"] == "FAILED"
    finally:
        engine.dispose()
