"""Private fixed parser entry; no shell, model, business writes or database sessions."""

import hashlib
import json
import sys
from pathlib import Path


def main():
    packet = sys.stdin.buffer.read(4097)
    if len(packet) > 4096:
        raise ValueError("Invalid startup packet")
    from app.modules.agent.import_process_limits import RESULT_BYTES, limit_child

    limit_child()
    from app.core.exceptions import AppError
    from app.modules.agent.import_inspection import InspectionManifest
    from app.modules.importer.intake import _inspect
    from app.modules.importer.limits import MAX_ARCHIVE_BYTES, MAX_TABLE_BYTES
    from app.modules.importer.zip_preview import expand_zip

    request = json.loads(packet)
    filename = request["filename"]
    with Path("input.bin").open("rb") as stream:
        content = stream.read(MAX_ARCHIVE_BYTES + 1)
    digest = hashlib.sha256(content).hexdigest()
    if digest != request["source_sha256"]:
        raise ValueError("Source changed")
    try:
        if filename.lower().endswith(".zip"):
            members = expand_zip(content, allow_template_notes=True)
        else:
            if len(content) > MAX_TABLE_BYTES:
                raise ValueError("Source too large")
            members = [(filename, content)]
        files: list[dict] = []
        seen: dict[str, int] = {}
        for number, (name, data) in enumerate(members, 1):
            fingerprint = hashlib.sha256(data).hexdigest()
            files.append(
                {
                    **_inspect(data, name),
                    "member_no": number,
                    "archive_member": name if filename.lower().endswith(".zip") else None,
                    "sha256": fingerprint,
                    "size_bytes": len(data),
                    "duplicate_of": seen.get(fingerprint),
                }
            )
            # Keep only bounded business guidance; never include arbitrary parser exception text.
            row = files[-1]
            if not data:
                row["blocked"] = True
            if row["blocked"]:
                row["message"] = "文件暂时无法识别，请检查格式或拆分工作表后重试"
            elif row["target"] is None:
                row["message"] = "未能唯一识别资料类型，请选择后继续核对"
            else:
                row["message"] = row["message"][:512]
            seen.setdefault(fingerprint, number)
        manifest = InspectionManifest.model_validate(
            {
                "protocol_version": 1,
                "source_sha256": digest,
                "files": files,
                "business_data_applied": False,
            }
        )
        raw = manifest.model_dump_json().encode()
        if len(raw) > RESULT_BYTES:
            raise ValueError("Result too large")
    except AppError:
        raw = b'{"error":"INVALID_SOURCE"}'
    Path("result.json").write_bytes(raw)


if __name__ == "__main__":
    main()
