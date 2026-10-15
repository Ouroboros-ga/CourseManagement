"""Deploy an accepted immutable R6 bundle with backup and automatic application rollback.

Existing records and feature gates are preserved. Enabling the two business gates
is a separate, explicit operation after ownership/classification/member readiness.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from deploy_confirmed_modules_20261015 import (
    ROOT,
    counts,
    ready,
    relocate_launchers,
    sql,
    switch,
)
from dotenv import dotenv_values

HEAD = "f26a1016a003"


def verify_files(base, files):
    for relative, expected in files.items():
        path = (base / relative).resolve()
        assert path.is_relative_to(base.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative


def main():
    manifest_path, archive, web_archive, evidence_path = map(Path, sys.argv[1:])
    manifest = json.loads(manifest_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    assert evidence["test_exit_code"] == 0 and evidence["test_schema_removed"]
    assert evidence["migration"]["original_data_unchanged"]
    assert all(stage["exit_code"] == 0 for stage in evidence["migration"]["stages"])
    assert evidence["source_bundle_sha256"] == manifest["backend_sha256"]
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
    for path, key in ((archive, "backend_sha256"), (web_archive, "web_sha256")):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[key]
    old = (ROOT / "current").resolve()
    old_web = (ROOT / "admin-web/current").resolve()
    initial_head = sql("SELECT version_num FROM course_management.alembic_version")
    assert initial_head in {"f26a1015h001", HEAD}, (
        "Unexpected live schema; refresh rehearsal first"
    )
    release = "20261016-campus-r6-" + manifest["source_commit"][:10]
    candidate = ROOT / "releases" / release
    web = ROOT / "admin-web/releases" / release
    assert not candidate.exists() and not web.exists()
    for path in (candidate, web):
        path.mkdir(mode=0o755)
    for path, destination in ((archive, candidate), (web_archive, web)):
        with tarfile.open(path) as bundle:
            bundle.extractall(destination, filter="data")
    verify_files(candidate, manifest["source_files"])
    verify_files(web, manifest["web_files"])
    # Older browser tabs can still resolve the immediately previous hashed chunks.
    for path in (old_web / "assets").iterdir():
        if path.is_file() and not (web / "assets" / path.name).exists():
            shutil.copyfile(path, web / "assets" / path.name)
    for base in (candidate, web):
        for path in base.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
    backend = candidate / "backend"
    assert (backend / "uv.lock").read_bytes().replace(b"\r\n", b"\n") == (
        old / "backend/uv.lock"
    ).read_bytes().replace(b"\r\n", b"\n")
    subprocess.run(
        ["cp", "-a", str(old / "backend/.venv"), str(backend / ".venv")], check=True
    )
    relocate_launchers(old / "backend/.venv", backend / ".venv")
    config = Path("/etc/course-management/backend.env")
    old_config = config.read_bytes()
    runtime = {
        **os.environ,
        **{k: v for k, v in dotenv_values(config).items() if v is not None},
        "PYTHONPATH": str(backend),
    }
    migration = {
        **runtime,
        **{
            k: v
            for k, v in dotenv_values("/etc/course-management/migration.env").items()
            if v is not None
        },
    }
    from sqlalchemy.engine import make_url

    assert make_url(runtime["DATABASE_URL"]).database == "course_management"
    assert make_url(migration["DATABASE_URL"]).database == "course_management"
    user = make_url(runtime["DATABASE_URL"]).username
    assert user and re.fullmatch(r"[a-zA-Z0-9_]+", user)
    flags = {
        key: runtime.get(key, "false")
        for key in (
            "CAMPUS_CONFIGURATION_ENABLED",
            "CAMPUS_ACADEMIC_SCOPED_ENABLED",
            "ACADEMIC_PUBLICATION_ENABLED",
            "CAMPUS_BUSINESS_SCOPED_ENABLED",
            "CAMPUS_SCHEDULING_ENABLED",
        )
    }
    report = {
        **manifest,
        "release": release,
        "previous_backend": str(old),
        "previous_web": str(old_web),
        "previous_migration_head": initial_head,
        "migration_head": HEAD,
        "flags": flags,
        "rehearsal": str(evidence_path),
        "schema_rollback": "retain additive schema; use backup for full restoration",
    }
    (candidate / "backend.env.before").write_bytes(old_config)
    (candidate / "backend.env.before").chmod(0o600)
    stopped = switched = False
    process = None
    try:
        subprocess.run(["systemctl", "stop", "course-management"], check=True)
        stopped = True
        backup_output = (
            subprocess.check_output(["bash", str(ROOT / "backup.sh")]).decode().strip()
        )
        match = re.fullmatch(
            r"Backup completed: (/var/backups/course-management/\d{8}T\d{6}Z\.[A-Za-z0-9]+)",
            backup_output,
        )
        assert match, "Backup output did not identify a verified recovery point"
        subprocess.run(
            ["sha256sum", "-c", "SHA256SUMS"],
            cwd=match[1],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        report["backup"] = match[1]
        before = counts()
        existing = set(sql("SHOW TABLES FROM course_management").splitlines())
        subprocess.run(
            [str(backend / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"],
            cwd=backend,
            env=migration,
            check=True,
        )
        assert sql("SELECT version_num FROM course_management.alembic_version") == HEAD
        created = set(sql("SHOW TABLES FROM course_management").splitlines()) - existing
        for table in sorted(created):
            assert re.fullmatch(r"[a-z_]+", table)
            sql(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON course_management.`{table}` TO '{user}'@'%'"
            )
        assert counts() == before, "Unexpected existing business row count change"
        probe = """from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.core.config import get_settings
import app.models
from app.modules.academic.models import TeachingClass
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.time_models import SchoolSemesterDefault
from app.modules.volunteer.preparation_models import GroupSemesterPreparation
from app.modules.inspection.responsibility import InspectionResponsibility
from app.modules.organization.models import ScopedGrant
with Session(create_engine(get_settings().database_url)) as db:
    for model in (TeachingClass,AcademicOffering,SchoolSemesterDefault,GroupSemesterPreparation,InspectionResponsibility,ScopedGrant):
        db.scalars(select(model).limit(1)).first()
print('Runtime app role schema reads passed')
"""
        subprocess.run(
            [str(backend / ".venv/bin/python"), "-c", probe],
            cwd=backend,
            env=runtime,
            check=True,
            timeout=45,
        )
        with (candidate / "candidate.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    str(backend / ".venv/bin/uvicorn"),
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18016",
                    "--no-access-log",
                ],
                cwd=backend,
                env=runtime,
                stdout=log,
                stderr=log,
                user="course-management",
                group="course-management",
            )
            ready("http://127.0.0.1:18016/health/ready")
            process.terminate()
            process.wait(timeout=15)
            process = None
        # No credentials, data mappings or production gates are silently rewritten.
        assert config.read_bytes() == old_config
        switch(ROOT / "current", candidate)
        switched = True
        switch(ROOT / "admin-web/current", web)
        subprocess.run(["systemctl", "start", "course-management"], check=True)
        stopped = False
        for url in (
            "http://127.0.0.1:8011/health/ready",
            "https://course.zsitai.xyz/health/ready",
        ):
            ready(url)
        # vol is an HTTP redirect alias, not a separately configured TLS service.
        with urllib.request.urlopen("http://vol.zsitai.xyz/", timeout=10) as response:
            assert response.geturl() == "https://course.zsitai.xyz/"
            assert (
                hashlib.sha256(response.read()).hexdigest()
                == manifest["web_files"]["index.html"]
            )
        with urllib.request.urlopen("http://127.0.0.1:8011/openapi.json") as response:
            paths = json.load(response)["paths"]
        assert "/api/v1/colleges/{cid}/imports/confirmation-set/confirm" in paths
        assert (
            "/api/v1/colleges/{cid}/academic/teaching-classes/{tid}/shared-identity/confirm"
            in paths
        )
        assert "/api/v1/me/timetable/entries/{eid}/restore" in paths
        assert counts() == before
        verify_files(candidate, manifest["source_files"])
        verify_files(web, manifest["web_files"])
        report.update(
            status="passed",
            business_counts_unchanged=True,
            added_tables=sorted(created),
            runtime_schema_sql_probe=True,
        )
    except Exception:
        if process:
            process.terminate()
            process.wait(timeout=15)
        if switched:
            switch(ROOT / "current", old)
            switch(ROOT / "admin-web/current", old_web)
        if stopped or switched:
            subprocess.run(["systemctl", "restart", "course-management"], check=True)
            ready("http://127.0.0.1:8011/health/ready")
        report.update(
            status="failed", application_rollback=True, additive_schema_retained=True
        )
        raise
    finally:
        (candidate / "CAMPUS_RELEASE.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key not in {"source_files", "web_files"}
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
