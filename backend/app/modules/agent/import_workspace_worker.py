"""Dedicated source consumer; storage and bounded parser run outside database sessions."""

import time

from app.core.config import get_settings
from app.modules.agent.import_inspection import InspectionError, inspect_source, validate_source
from app.modules.agent.import_preview_process import run_preview_claim
from app.modules.agent.import_workspace import ImportWorkspaceService
from app.modules.file.storage import build_default_storage


class ImportWorkspaceWorker:
    def __init__(
        self,
        session_factory,
        connections,
        *,
        environment,
        app_key_id,
        storage=None,
        inspector=inspect_source,
        preview_executor=run_preview_claim,
    ):
        self.session_factory, self.connections = session_factory, connections
        self.environment, self.app_key_id = environment, app_key_id
        self.storage = storage if storage is not None else build_default_storage(get_settings())
        self.inspector = inspector
        self.preview_executor = preview_executor

    def _service(self, db):
        return ImportWorkspaceService(
            db,
            self.connections,
            environment=self.environment,
            app_key_id=self.app_key_id,
            storage=self.storage,
        )

    def run_once(self):
        if (
            not get_settings().agent_tools_enabled
            or not get_settings().agent_import_workspace_enabled
        ):
            return False
        with self.session_factory() as db:
            service = self._service(db)
            claim = service.claim()
            changed = service.changed
        if claim is None:
            return changed
        inspection, code = None, None
        try:
            content = self.storage.read(claim.object_key)
            fingerprint = validate_source(content, claim.filename)
            if fingerprint != claim.sha256 or len(content) != claim.size_bytes:
                code = "SOURCE_CHANGED"
            elif claim.stage == "PREVIEW":
                self.preview_executor(
                    claim,
                    content,
                    connections=self.connections,
                    environment=self.environment,
                    app_key_id=self.app_key_id,
                )
                return True
            else:
                inspection = self.inspector(content, claim.filename)
        except InspectionError as error:
            code = error.code
        except Exception:
            code = "IMPORT_INSPECTION_FAILED"
        with self.session_factory() as db:
            self._service(db).finish(claim, inspection, error_code=code)
        return True


def main():
    import argparse

    from app.core.database import get_session_factory

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not (
        settings.agent_worker_enabled
        and settings.agent_tools_enabled
        and settings.agent_import_workspace_enabled
    ):
        raise SystemExit("Import workspace worker is disabled")
    if settings.agent_management_chat_config is None:
        raise SystemExit("Management tool application is not configured")
    worker = ImportWorkspaceWorker(
        get_session_factory(),
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=settings.agent_management_chat_config.tool_app_key_id,
    )
    try:
        while True:
            changed = worker.run_once()
            if args.once:
                return
            if not changed:
                time.sleep(0.5)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
