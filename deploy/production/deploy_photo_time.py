"""Root-only bounded hotfix deployment, preserving the independently released baseline.

Arguments: backend archive, backend sha256, Web archive, Web sha256.
No migrations or production business writes. On failed verification restore both pointers.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

RELEASE = "20261014-photo-time-r2"
EXPECTED_BACKEND = "/opt/course-management/releases/20261014-photo-time"
EXPECTED_WEB = "/opt/course-management/admin-web/releases/20261014-photo-time"


def ready(url):
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=2) as reply:
                assert json.load(reply)["database"] == "up"
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Readiness failed")


def switch(pointer, target):
    pending = pointer.with_name(pointer.name + ".photo-time-pending")
    if pending.exists() or pending.is_symlink():
        raise RuntimeError("Pending pointer exists")
    pending.symlink_to(target)
    os.replace(pending, pointer)


def main():
    backend_archive, backend_hash, web_archive, web_hash = sys.argv[1:]
    for archive, digest in [(backend_archive, backend_hash), (web_archive, web_hash)]:
        assert hashlib.sha256(Path(archive).read_bytes()).hexdigest() == digest, "Archive checksum"
    root = Path("/opt/course-management")
    pointer = root / "current"
    web_pointer = root / "admin-web/current"
    old = pointer.resolve()
    old_web = web_pointer.resolve()
    assert str(old) == EXPECTED_BACKEND and str(old_web) == EXPECTED_WEB, "Baseline changed"
    new = root / "releases" / RELEASE
    new_web = root / "admin-web/releases" / RELEASE
    assert not new.exists() and not new_web.exists(), "Release already exists"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 18011))
    shutil.copytree(old, new, symlinks=True)
    with tarfile.open(backend_archive) as bundle:
        allowed = {"PATCH_MANIFEST.json"} | {
            "backend/app/modules/" + name for name in [
                "attendance/repository.py", "attendance/schemas.py", "attendance/service.py",
                "attendance/router.py", "attendance/evidence.py", "file/repository.py", "file/service.py"
            ]
        }
        assert set(bundle.getnames()) == allowed, "Patch scope"
        bundle.extractall(new, filter="data")
    new_web.mkdir(mode=0o755)
    with tarfile.open(web_archive) as bundle:
        bundle.extractall(new_web, filter="data")
    for path in new_web.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    for path in (new / "app",):
        assert not path.exists()
    for path in (new / "backend/app").rglob("*.py"):
        path.chmod(0o644)
    env = dict(os.environ)
    env.update({k: str(v) for k, v in dotenv_values("/etc/course-management/backend.env").items()
                if v is not None})
    report = {"release": RELEASE, "previous_backend": str(old), "previous_web": str(old_web),
              "backend_sha256": backend_hash, "web_sha256": web_hash,
              "database_migration": False, "checks": []}
    python = str(new / "backend/.venv/bin/python")
    log = (new / "candidate.log").open("wb")
    process = None
    switched = False
    try:
        # Offline fixture + actual runtime imports; production database is not mutated.
        subprocess.run([python, "/tmp/cm-verify-photo-time.py", "synthetic"], cwd=new / "backend",
                       env=env, check=True)
        report["checks"].append("synthetic_http_and_signed_download")
        process = subprocess.Popen(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", "18011", "--no-access-log"],
            cwd=new / "backend", env=env, stdout=log, stderr=log,
            user="course-management", group="course-management",
        )
        ready("http://127.0.0.1:18011/health/ready")
        report["checks"].append("candidate_ready_as_service_user")
        process.terminate()
        process.wait(timeout=15)
        process = None
        assert pointer.resolve() == old and web_pointer.resolve() == old_web, "Concurrent release"
        switch(pointer, new)
        switched = True
        switch(web_pointer, new_web)
        subprocess.run(["systemctl", "restart", "course-management"], check=True)
        ready("http://127.0.0.1:8011/health/ready")
        ready("https://course.zsitai.xyz/health/ready")
        report["checks"].append("public_backend_ready")
        subprocess.run([python, "/tmp/cm-verify-photo-time.py", "live"], cwd=new / "backend",
                       env=env, check=True)
        report["checks"].append("live_readonly_evidence_and_web_assets")
        report["passed"] = True
        (new / "PHOTO_TIME_RELEASE.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    except Exception:
        if switched:
            switch(pointer, old)
            switch(web_pointer, old_web)
            subprocess.run(["systemctl", "restart", "course-management"], check=True)
            ready("http://127.0.0.1:8011/health/ready")
        print(json.dumps({"passed": False, "rolled_back": switched}))
        raise
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
