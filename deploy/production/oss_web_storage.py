"""Private OSS preflight, verified local-file migration and exact Web CORS/CSP.

Run with the release's Python and PYTHONPATH=backend. Credentials stay in --env.
Migration reads file metadata only; no database writes or local deletes. --apply
is required to copy objects or change CORS. Output never contains signed URLs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

import alibabacloud_oss_v2 as oss
from app.core.config import Settings
from app.modules.file.storage import LocalStorage, ObjectStorage

WEB_ORIGIN = "https://course.zsitai.xyz"


def web_csp(origin: str) -> str:
    if not re.fullmatch(
        r"https://[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.oss-[a-z0-9-]+\.aliyuncs\.com",
        origin,
    ):
        raise ValueError("invalid public OSS origin")
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
        f"img-src 'self' data: blob: {origin}; connect-src 'self' {origin}; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )


def migrate_files(records, source, target, *, apply: bool) -> dict[str, int]:
    counts = {"verified_local": 0, "copied": 0, "verified_remote": 0, "bytes": 0}
    for row in records:
        if not source.exists(row.object_key):
            raise RuntimeError("registered local file missing; migration stopped")
        body = source.read(row.object_key)
        if (
            len(body) != row.size_bytes
            or hashlib.sha256(body).hexdigest() != row.sha256
        ):
            raise RuntimeError("local integrity mismatch; migration stopped")
        counts["verified_local"] += 1
        counts["bytes"] += len(body)
        if not apply:
            continue
        if target.exists(row.object_key):
            remote = target.read(row.object_key)
            if (
                len(remote) != row.size_bytes
                or hashlib.sha256(remote).hexdigest() != row.sha256
            ):
                raise RuntimeError("remote integrity mismatch; object not overwritten")
        else:
            target.save(row.object_key, body, row.content_type)
            counts["copied"] += 1
        verified = target.read(row.object_key)
        if (
            len(verified) != row.size_bytes
            or hashlib.sha256(verified).hexdigest() != row.sha256
        ):
            raise RuntimeError("remote integrity verification failed")
        counts["verified_remote"] += 1
    return counts


def preflight(store: ObjectStorage) -> dict:
    key = "preflight/web-direct-" + secrets.token_hex(16) + ".png"
    body = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS9sAAAAASUVORK5CYII="
    )
    result = {}
    try:
        store.save(key, body, "image/png")
        assert store.read(key) == body, "roundtrip failed"
        signed = store.presign_direct_get(key, 30)
        request = urllib.request.Request(signed.url, headers={"Origin": WEB_ORIGIN})
        with urllib.request.urlopen(request, timeout=20) as response:
            assert response.read() == body and response.status == 200
            assert response.headers.get_content_type() == "image/png"
            assert response.headers.get("Cache-Control") == "private, no-store"
            result["cors_origin"] = response.headers.get("Access-Control-Allow-Origin")
            result["signed_get"] = True
        try:
            with urllib.request.urlopen(signed.url.split("?", 1)[0], timeout=20):
                raise RuntimeError("anonymous access allowed; abort")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, "unexpected anonymous result"
        result["anonymous_denied"] = True
        acl = store._call(
            "get_bucket_acl", oss.GetBucketAclRequest(bucket=store._bucket)
        )
        assert acl.acl == "private", "bucket must remain private"
        result["bucket_private"] = True
    finally:
        store.delete(key)
        assert not store.exists(key), "preflight cleanup failed"
    result["cleanup"] = True
    return result


def cors_config(store: ObjectStorage):
    try:
        result = store._client.get_bucket_cors(
            oss.GetBucketCorsRequest(bucket=store._bucket)
        )
        return result.cors_configuration
    except Exception as exc:  # noqa: BLE001 - SDK 错误需脱敏，只有明确的缺配置允许创建。
        unwrap = getattr(exc, "unwrap", None)
        inner = unwrap() if callable(unwrap) else exc
        if getattr(inner, "code", None) == "NoSuchCORSConfiguration":
            return None
        raise RuntimeError("cannot read bucket CORS; not changed") from None


def configure_cors(store: ObjectStorage, backup: Path, *, apply: bool) -> dict:
    current = cors_config(store)
    rules = list(current.cors_rules or []) if current else []
    if any(
        WEB_ORIGIN in (r.allowed_origins or [])
        and {"GET", "HEAD"} <= set(r.allowed_methods or [])
        for r in rules
    ):
        return {"cors": "already_configured", "rules": len(rules)}
    if not apply:
        return {"cors": "requires_exact_origin_rule", "rules": len(rules)}
    if backup.exists():
        raise RuntimeError("CORS backup already exists; refusing overwrite")
    payload = {
        "absent": current is None,
        "response_vary": current.response_vary if current else None,
        "rules": [
            {
                name: getattr(r, name, None)
                for name in (
                    "allowed_origins",
                    "allowed_methods",
                    "allowed_headers",
                    "expose_headers",
                    "max_age_seconds",
                )
            }
            for r in rules
        ],
    }
    backup.write_text(json.dumps(payload, indent=2) + "\n")
    backup.chmod(0o600)
    rules.append(
        oss.CORSRule(
            allowed_origins=[WEB_ORIGIN],
            allowed_methods=["GET", "HEAD"],
            expose_headers=["Content-Type", "Content-Length"],
            max_age_seconds=300,
        )
    )
    store._call(
        "put_bucket_cors",
        oss.PutBucketCorsRequest(
            bucket=store._bucket,
            cors_configuration=oss.CORSConfiguration(
                cors_rules=rules, response_vary=True
            ),
        ),
    )
    return {"cors": "configured", "rules": len(rules)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["preflight", "migrate", "cors", "restore-cors", "csp"]
    )
    parser.add_argument("--env", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    # 验证 object 必需配置；迁移不得触发本地镜像重写。
    settings = Settings(
        _env_file=args.env,
        FILE_STORAGE_BACKEND="object",
        OSS_LOCAL_MIRROR_ENABLED=False,
    )
    if args.command == "csp":
        print(
            'add_header Content-Security-Policy "'
            + web_csp(
                f"https://{settings.oss_bucket}.oss-{settings.oss_region}.aliyuncs.com"
            )
            + '" always;'
        )
        return
    store = ObjectStorage(settings)
    if args.command == "preflight":
        result = preflight(store)
    elif args.command in ("cors", "restore-cors"):
        if not args.backup:
            parser.error("cors requires --backup")
        if args.command == "cors":
            result = configure_cors(store, args.backup, apply=args.apply)
        else:
            saved = json.loads(args.backup.read_text())
            if args.apply:
                if saved["absent"]:
                    store._call(
                        "delete_bucket_cors",
                        oss.DeleteBucketCorsRequest(bucket=store._bucket),
                    )
                else:
                    store._call(
                        "put_bucket_cors",
                        oss.PutBucketCorsRequest(
                            bucket=store._bucket,
                            cors_configuration=oss.CORSConfiguration(
                                cors_rules=[oss.CORSRule(**r) for r in saved["rules"]],
                                response_vary=saved["response_vary"],
                            ),
                        ),
                    )
            result = {"cors": "restored" if args.apply else "restore_pending"}
    else:
        import app.models  # noqa: F401
        from app.modules.file.models import FileObject
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        engine = create_engine(settings.database_url)
        with Session(engine) as session:
            rows = session.scalars(
                select(FileObject)
                .where(FileObject.status == "READY")
                .order_by(FileObject.id)
                .execution_options(yield_per=100)
            )
            source = LocalStorage(settings.file_local_storage_dir, settings.secret_key)
            result = migrate_files(rows, source, store, apply=args.apply)
        engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 命令行禁止泄漏带签名 URL 的原始异常。
        # SDK/urllib 异常文本可能含签名，不能直接输出异常或 traceback。
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
