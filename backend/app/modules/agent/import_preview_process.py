"""One fixed, bounded backend preview claim; never a model-selected process or command."""

import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

PACKET_BYTES = 1024 * 1024


def run_preview_claim(claim, content, *, connections, environment, app_key_id, timeout_seconds=60):
    from app.core.config import get_settings
    from app.modules.agent.import_inspection import InspectionError, _environment, _interpreter
    from app.modules.agent.import_process_limits import contain_process

    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        raise InspectionError("IMPORT_PREVIEW_FAILED")
    # This is a trusted backend worker, requiring its deployment DB credentials. Transfer
    # config only through the private pipe, never argv, logs, result files or model context.
    configuration = get_settings().model_dump(mode="json", by_alias=True)
    configuration["AGENT_TOOL_CONNECTIONS"] = [c.model_dump(mode="json") for c in connections]
    packet = json.dumps(
        {
            "settings": configuration,
            "claim": asdict(claim),
            "environment": environment,
            "app_key_id": app_key_id,
        }
    ).encode()
    if len(packet) > PACKET_BYTES:
        raise InspectionError("IMPORT_PREVIEW_FAILED")
    with tempfile.TemporaryDirectory(prefix="course-preview-") as folder:
        (Path(folder) / "input.bin").write_bytes(content)
        process = None
        try:
            process = subprocess.Popen(
                [_interpreter(), "-S", "-m", "app.modules.agent.import_preview_process"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=folder,
                env=_environment(),
                shell=False,
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            with contain_process(process.pid):
                process.communicate(packet, timeout=timeout_seconds)
                if process.returncode != 0:
                    raise InspectionError("IMPORT_PREVIEW_FAILED")
        except subprocess.TimeoutExpired:
            raise InspectionError("IMPORT_PREVIEW_TIMEOUT") from None
        except OSError:
            raise InspectionError("IMPORT_PREVIEW_FAILED") from None
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()


def main():
    packet = sys.stdin.buffer.read(PACKET_BYTES + 1)
    if len(packet) > PACKET_BYTES:
        raise ValueError("Invalid preview packet")
    from app.modules.agent.import_process_limits import limit_child

    limit_child()
    request = json.loads(packet)
    # Import settings only after containment. The temporary cwd has no deployment .env.
    for name, value in request["settings"].items():
        if value is not None:
            os.environ[name] = value if isinstance(value, str) else json.dumps(value)
    from app.core.config import get_settings
    from app.core.database import get_session_factory
    from app.modules.agent.import_inspection import validate_source
    from app.modules.agent.import_workspace import ImportClaim, ImportWorkspaceService
    from app.modules.importer.limits import MAX_ARCHIVE_BYTES

    settings = get_settings()
    if not settings.agent_tools_enabled or not settings.agent_import_workspace_enabled:
        raise ValueError("Preview is disabled")
    claim = ImportClaim(**request["claim"])
    if claim.stage != "PREVIEW":
        raise ValueError("Wrong preview stage")
    with Path("input.bin").open("rb") as stream:
        content = stream.read(MAX_ARCHIVE_BYTES + 1)
    if validate_source(content, claim.filename) != claim.sha256 or len(content) != claim.size_bytes:
        raise ValueError("Source changed")
    with get_session_factory()() as db:
        service = ImportWorkspaceService(
            db,
            settings.agent_tool_connections,
            environment=request["environment"],
            app_key_id=request["app_key_id"],
        )
        service.execute_previews(claim, content)


if __name__ == "__main__":
    main()
