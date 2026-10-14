"""Bounded unified release after isolated MySQL upgrade/downgrade rehearsal.

No college business flags are enabled. On failure restore application pointers,
keeping additive schema for compatibility; never delete production business data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path("/opt/course-management")
RELEASE = "20261014-unified"
NEW_HEAD = "f26a1014m001"
OLD_HEAD = "181729fc7239"
TABLES = ["school", "college", "scoped_grant", "course_type", "volunteer_group",
          "group_config_version", "group_scope_type"]


def sql(statement):
    return subprocess.check_output([
        "docker", "exec", "-i", "course-management-mysql", "mysql",
        "--defaults-extra-file=/run/cm-root.cnf", "-N",
    ], input=statement.encode()).decode().strip()


def ready(url):
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                assert json.load(response)["database"] == "up"
            return
        except (urllib.error.URLError, TimeoutError, AssertionError):
            time.sleep(0.3)
    raise RuntimeError("Readiness failed")


def switch(pointer, destination):
    temporary = pointer.with_name(pointer.name + ".unified-pending")
    assert not temporary.exists() and not temporary.is_symlink()
    temporary.symlink_to(destination)
    os.replace(temporary, pointer)


def main():
    manifest_file, web_archive, rehearsal_file = map(Path, sys.argv[1:])
    manifest = json.loads(manifest_file.read_text())
    rehearsal = json.loads(rehearsal_file.read_text())
    assert rehearsal["status"] == "passed"
    assert rehearsal["candidate_sha256"] == manifest["backend_sha256"]
    assert rehearsal["candidate_head"] == NEW_HEAD and rehearsal["source_head"] == OLD_HEAD
    new = ROOT / "releases" / RELEASE
    python = str(new / "backend/.venv/bin/python")
    for name, digest in manifest["source_files"].items():
        assert hashlib.sha256((new / name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256(web_archive.read_bytes()).hexdigest() == manifest["web_sha256"]
    old = (ROOT / "current").resolve()
    old_web = (ROOT / "admin-web/current").resolve()
    assert old.name == "20261014-photo-time-r2" and old_web.name == old.name
    initial_head = sql("SELECT version_num FROM course_management.alembic_version;")
    assert initial_head in {OLD_HEAD, NEW_HEAD}, "Unexpected production migration"
    runtime_env = dict(os.environ)
    runtime_env.update({k: str(v) for k, v in dotenv_values("/etc/course-management/backend.env").items()
                        if v is not None})
    for flag in ["CAMPUS_CONFIGURATION_ENABLED", "CAMPUS_ACADEMIC_SCOPED_ENABLED"]:
        assert runtime_env.get(flag, "false").lower() in {"false", "0", "off"}, flag
    user = make_url(runtime_env["DATABASE_URL"]).username
    assert user and re.fullmatch(r"[A-Za-z0-9_]+", user)
    hosts = sql(f"SELECT Host FROM mysql.user WHERE User='{user}';").splitlines()
    assert hosts == ["%"], "Review runtime account host before granting"
    migration_env = dict(runtime_env)
    migration_env.update({k: str(v) for k, v in dotenv_values("/etc/course-management/migration.env").items()
                          if v is not None})
    assert make_url(migration_env["DATABASE_URL"]).database == "course_management"
    new_web = ROOT / "admin-web/releases" / RELEASE
    new_web.mkdir(mode=0o755, exist_ok=True)
    with tarfile.open(web_archive) as bundle:
        if (new_web / "index.html").exists():
            assert (new_web / "index.html").read_bytes() == bundle.extractfile("index.html").read()
        bundle.extractall(new_web, filter="data")
    # Keep older hashed assets available for tabs opened before this release.
    for source in (old_web / "assets").iterdir():
        destination = new_web / "assets" / source.name
        if source.is_file() and not destination.exists():
            destination.write_bytes(source.read_bytes())
    for path in new_web.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    backup_output = subprocess.check_output(["bash", str(ROOT / "backup.sh")]).decode().strip()
    print(backup_output)
    report = {"release": RELEASE, "previous_backend": str(old), "previous_web": str(old_web),
              "previous_head": initial_head, "migration_head": NEW_HEAD,
              "backup": backup_output, "backend_sha256": manifest["backend_sha256"],
              "web_sha256": manifest["web_sha256"], "college_flags_enabled": False,
              "checks": [], "rehearsal": str(rehearsal_file)}
    stopped = switched = False
    candidate = None
    log = (new / "candidate.log").open("wb")
    try:
        assert (ROOT / "current").resolve() == old and (ROOT / "admin-web/current").resolve() == old_web
        subprocess.run(["systemctl", "stop", "course-management"], check=True)
        stopped = True
        subprocess.run([python, "-m", "alembic", "upgrade", "head"],
                       cwd=new / "backend", env=migration_env, check=True)
        assert sql("SELECT version_num FROM course_management.alembic_version;") == NEW_HEAD
        for table in TABLES:
            sql(f"GRANT SELECT,INSERT,UPDATE,DELETE ON course_management.`{table}` TO '{user}'@'%';")
        report["checks"].append("additive_migration_and_scoped_runtime_grants")
        subprocess.run([python, "/tmp/cm-verify-photo-time.py", "synthetic"],
                       cwd=new / "backend", env=runtime_env, check=True)
        subprocess.run([python, "/opt/course-management/verify_runtime_permissions.py"],
                       cwd=new / "backend", env={**runtime_env, "PYTHONPATH": str(new / "backend")}, check=True)
        candidate = subprocess.Popen([python, "-m", "uvicorn", "app.main:app", "--host",
                                      "127.0.0.1", "--port", "18011", "--no-access-log"],
                                     cwd=new / "backend", env=runtime_env, stdout=log, stderr=log,
                                     user="course-management", group="course-management")
        ready("http://127.0.0.1:18011/health/ready")
        candidate.terminate()
        candidate.wait(timeout=15)
        candidate = None
        switch(ROOT / "current", new)
        switched = True
        switch(ROOT / "admin-web/current", new_web)
        subprocess.run(["systemctl", "start", "course-management"], check=True)
        stopped = False
        ready("http://127.0.0.1:8011/health/ready")
        ready("https://course.zsitai.xyz/health/ready")
        subprocess.run([python, "/tmp/cm-verify-unified.py"], cwd=new / "backend",
                       env=runtime_env, check=True)
        report["checks"].append("runtime_user_public_readonly_acceptance")
        report["passed"] = True
        (new / "UNIFIED_RELEASE.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    except Exception:
        if switched:
            switch(ROOT / "current", old)
            switch(ROOT / "admin-web/current", old_web)
        if stopped or switched:
            subprocess.run(["systemctl", "restart", "course-management"], check=True)
            ready("http://127.0.0.1:8011/health/ready")
        print(json.dumps({"passed": False, "application_restored": stopped or switched,
                          "schema_rollback": False}))
        raise
    finally:
        if candidate is not None:
            candidate.terminate()
            candidate.wait(timeout=15)
        log.close()


if __name__ == "__main__":
    main()
