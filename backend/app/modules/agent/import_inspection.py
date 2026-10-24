"""Fixed, resource-bounded source inspection for the forthcoming import workspace worker."""

import hashlib
import json
import math
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.modules.agent.import_process_limits import RESULT_BYTES, contain_process
from app.modules.importer.limits import (
    MAX_ARCHIVE_BYTES,
    MAX_EXPANDED_BYTES,
    MAX_QUEUE_FILES,
    MAX_TABLE_BYTES,
)

Target = Literal[
    "admin_roster",
    "faculty_staff",
    "class_responsibility",
    "timetable",
    "grid_timetable",
    "volunteer",
    "roster",
    "elective_course",
    "teaching_assignment",
]


class InspectionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ManifestMember(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    member_no: int = Field(ge=1, le=MAX_QUEUE_FILES)
    filename: str = Field(min_length=1, max_length=255)
    archive_member: str | None
    target: Target | None
    blocked: bool
    message: str = Field(max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=MAX_TABLE_BYTES)
    duplicate_of: int | None = Field(ge=1, le=MAX_QUEUE_FILES)


class InspectionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal[1]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    business_data_applied: Literal[False]
    files: list[ManifestMember] = Field(min_length=1, max_length=MAX_QUEUE_FILES)

    @model_validator(mode="after")
    def validate_members(self):
        if sum(row.size_bytes for row in self.files) > MAX_EXPANDED_BYTES:
            raise ValueError("Expanded source budget exceeded")
        previous: dict[int, ManifestMember] = {}
        names = set()
        for index, row in enumerate(self.files, 1):
            if row.size_bytes == 0 and not row.blocked:
                raise ValueError("Empty members require review")
            if row.member_no != index or row.filename in names:
                raise ValueError("Invalid member sequence")
            if row.archive_member is not None and row.archive_member != row.filename:
                raise ValueError("Invalid archive member")
            if row.duplicate_of is not None:
                original = previous.get(row.duplicate_of)
                if (
                    original is None
                    or original.sha256 != row.sha256
                    or original.size_bytes != row.size_bytes
                ):
                    raise ValueError("Invalid duplicate source")
            names.add(row.filename)
            previous[index] = row
        return self


def _environment():
    # No deployment DB, CAM, storage, proxy, Python startup hook or model credentials.
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys(
            [
                str(Path(__file__).resolve().parents[3]),
                sysconfig.get_path("purelib"),
                sysconfig.get_path("platlib"),
            ]
        )
    )
    result["PYTHONUTF8"] = "1"
    result["PYTHONNOUSERSITE"] = "1"
    return result


def _interpreter():
    # Bypass Windows uv/venv launchers: a child created before Job assignment could escape it.
    path = Path(sys.base_prefix, "python.exe") if sys.platform == "win32" else Path(sys.executable)
    if not path.is_file():
        raise InspectionError("IMPORT_INSPECTION_UNAVAILABLE")
    return str(path)


def inspect_source(content: bytes, filename: str, *, timeout_seconds: float = 30) -> dict:
    if (
        not isinstance(content, bytes)
        or not content
        or not isinstance(filename, str)
        or not 1 <= len(filename) <= 255
        or any(ord(char) < 32 for char in filename)
        or Path(filename).suffix.lower() not in {".zip", ".xlsx", ".xls", ".csv"}
        or len(content)
        > (MAX_ARCHIVE_BYTES if filename.lower().endswith(".zip") else MAX_TABLE_BYTES)
    ):
        raise InspectionError("IMPORT_INSPECTION_INVALID")
    if (
        not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 60
    ):
        raise InspectionError("IMPORT_INSPECTION_INVALID")
    digest = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix="course-import-") as folder:
        root = Path(folder)
        (root / "input.bin").write_bytes(content)
        process = None
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                [_interpreter(), "-S", "-m", "app.modules.agent.import_inspection_process"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=root,
                env=_environment(),
                shell=False,
                close_fds=True,
                creationflags=flags,
            )
            # Child waits on stdin until its parent has attached the Windows Job Object.
            with contain_process(process.pid):
                process.communicate(
                    json.dumps({"filename": filename, "source_sha256": digest}).encode(),
                    timeout=timeout_seconds,
                )
                if process.returncode != 0:
                    raise InspectionError("IMPORT_INSPECTION_FAILED")
                path = root / "result.json"
                with path.open("rb") as stream:
                    raw = stream.read(RESULT_BYTES + 1)
                if len(raw) > RESULT_BYTES:
                    raise InspectionError("IMPORT_INSPECTION_FAILED")
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload == {"error": "INVALID_SOURCE"}:
                    raise InspectionError("IMPORT_INSPECTION_INVALID")
                result = InspectionManifest.model_validate(payload)
                if result.source_sha256 != digest:
                    raise InspectionError("IMPORT_INSPECTION_FAILED")
                return result.model_dump(mode="json")
        except subprocess.TimeoutExpired:
            raise InspectionError("IMPORT_INSPECTION_TIMEOUT") from None
        except (OSError, ValueError, ValidationError):
            raise InspectionError("IMPORT_INSPECTION_UNAVAILABLE") from None
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()
