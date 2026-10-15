"""Deploy the checked campus upgrade bundle, retaining additive schema on application rollback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path("/opt/course-management")
HEAD = "f26a1015h001"


def sql(statement):
    return subprocess.check_output(
        ["docker", "exec", "-i", "course-management-mysql", "mysql",
         "--defaults-extra-file=/run/cm-root.cnf", "-N"],
        input=statement.encode(),
    ).decode().strip()


def ready(url):
    for _ in range(50):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if json.load(response)["database"] == "up":
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Readiness failed")


def switch(pointer, destination):
    pending = pointer.with_name(pointer.name + ".campus-pending")
    assert not pending.exists() and not pending.is_symlink()
    pending.symlink_to(destination)
    os.replace(pending, pointer)


def counts():
    return {table: int(sql(f"SELECT COUNT(*) FROM course_management.`{table}`")) for table in (
        "student", "user_account", "administrative_class", "wechat_identity", "task_roster_member",
        "attendance_record", "inspection_task", "inspection_assignment",
        "personal_timetable", "enrollment_change", "student_enrollment",
    )}


def relocate_launchers(source, target):
    """Console scripts embed absolute interpreter paths even after copying a venv."""
    old, new = str(source).encode(), str(target).encode()
    for script in (target / "bin").iterdir():
        if script.is_symlink() or not script.is_file():
            continue
        value = script.read_bytes()
        first, separator, rest = value.partition(b"\n")
        if first.startswith(b"#!") and old in first:
            script.write_bytes(first.replace(old, new) + separator + rest)


def main():
    manifest_path, archive, web_archive, evidence_path = map(Path, sys.argv[1:])
    manifest, evidence = json.loads(manifest_path.read_text()), json.loads(evidence_path.read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_tree"])
    assert evidence["status"] == "passed" and evidence["candidate_head"] == HEAD
    assert evidence["candidate_sha256"] == manifest["backend_sha256"]
    for file, key in [(archive, "backend_sha256"), (web_archive, "web_sha256")]:
        assert hashlib.sha256(file.read_bytes()).hexdigest() == manifest[key]
    old, old_web = (ROOT / "current").resolve(), (ROOT / "admin-web/current").resolve()
    initial_head = sql("SELECT version_num FROM course_management.alembic_version")
    assert initial_head in {"f26a1015e001", HEAD}
    config = Path("/etc/course-management/backend.env")
    old_config = config.read_bytes()
    runtime = {**os.environ, **{k: v for k, v in dotenv_values(config).items() if v is not None}}
    migration = {**runtime, **{k: v for k, v in dotenv_values(
        "/etc/course-management/migration.env").items() if v is not None}}
    assert make_url(runtime["DATABASE_URL"]).database == "course_management"
    assert make_url(migration["DATABASE_URL"]).database == "course_management"
    user = make_url(runtime["DATABASE_URL"]).username
    assert user and re.fullmatch(r"[A-Za-z0-9_]+", user)
    assert sql(f"SELECT Host FROM mysql.user WHERE User='{user}'").splitlines() == ["%"]
    # Keep the exact pre-release gates; deployment is not campus rollout.
    flags = {key: runtime.get(key, "false") for key in (
        "CAMPUS_CONFIGURATION_ENABLED", "CAMPUS_ACADEMIC_SCOPED_ENABLED",
        "ACADEMIC_PUBLICATION_ENABLED", "CAMPUS_BUSINESS_SCOPED_ENABLED", "CAMPUS_SCHEDULING_ENABLED")}
    runtime.update(flags)
    migration.update(flags)
    release = "20261015-confirmed-modules-" + manifest["source_tree"][:10]
    candidate, web = ROOT / "releases" / release, ROOT / "admin-web/releases" / release
    assert not candidate.exists() and not web.exists()
    candidate.mkdir(mode=0o755)
    web.mkdir(mode=0o755)
    with tarfile.open(archive) as bundle:
        bundle.extractall(candidate, filter="data")
    with tarfile.open(web_archive) as bundle:
        bundle.extractall(web, filter="data")
    for source in (old_web / "assets").iterdir():
        if source.is_file() and not (web / "assets" / source.name).exists():
            shutil.copyfile(source, web / "assets" / source.name)
    for base in (candidate, web):
        for path in base.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
    runtime_backend = old / "backend"
    assert runtime_backend.joinpath("uv.lock").read_bytes().replace(b"\r\n", b"\n") == (
        candidate / "backend/uv.lock").read_bytes().replace(b"\r\n", b"\n")
    subprocess.run(["cp", "-a", str(runtime_backend / ".venv"), str(candidate / "backend/.venv")], check=True)
    relocate_launchers(runtime_backend / ".venv", candidate / "backend/.venv")
    python, backend = str(candidate / "backend/.venv/bin/python"), candidate / "backend"
    runtime["PYTHONPATH"] = migration["PYTHONPATH"] = str(backend)
    before = counts()
    existing = set(sql("SHOW TABLES FROM course_management").splitlines())
    report = {**manifest, "previous_backend": str(old), "previous_web": str(old_web),
              "release": release, "previous_migration_head": initial_head,
              "migration_head": HEAD, "flags": flags, "rehearsal": str(evidence_path)}
    (candidate / "backend.env.before").write_bytes(old_config)
    (candidate / "backend.env.before").chmod(0o600)
    process = None
    stopped = switched = False
    try:
        subprocess.run(["systemctl", "stop", "course-management"], check=True)
        stopped = True
        backup_output = subprocess.check_output(["bash", str(ROOT / "backup.sh")]).decode().strip()
        match = re.fullmatch(r"Backup completed: (/var/backups/course-management/\d{8}T\d{6}Z\.[A-Za-z0-9]+)", backup_output)
        assert match, "Unverified backup output; production was not stopped"
        subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=match[1], stdout=subprocess.DEVNULL, check=True)
        report["backup"] = match[1]
        before = counts()
        subprocess.run([python, "-m", "alembic", "upgrade", "head"], cwd=backend, env=migration, check=True)
        assert sql("SELECT version_num FROM course_management.alembic_version") == HEAD
        created = set(sql("SHOW TABLES FROM course_management").splitlines()) - existing
        for table in sorted(created):
            assert re.fullmatch(r"[a-z_]+", table)
            sql(f"GRANT SELECT,INSERT,UPDATE,DELETE ON course_management.`{table}` TO '{user}'@'%'")
        assert counts() == before, "Unexpected existing business row count change"
        # Read new ORM columns and the summary/notice SQL with the actual app role.
        probe = """from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.core.config import get_settings
import app.models
from app.modules.academic.models import Semester,Student
from app.modules.academic.campus_models import CourseType
from app.modules.academic.time_models import CollegeTimeProfile
from app.modules.timetable.models import PersonalTimetable
from app.modules.report.summary_router import aggregate
from app.modules.academic.notice_feed import personal_notices
from app.common.pagination import PageParams
with Session(create_engine(get_settings().database_url)) as db:
    for model in (CourseType,CollegeTimeProfile,PersonalTimetable):
        db.scalars(select(model).limit(1)).first()
    sid=db.scalar(select(Semester.id).limit(1))
    if sid: aggregate(db,sid,[],attendance=True)
    student=db.scalar(select(Student.id).limit(1))
    if student: personal_notices(db,student,PageParams(page=1,page_size=1))
print('Runtime schema and SQL read probe passed')
"""
        subprocess.run([python, "-c", probe], cwd=backend, env=runtime, check=True, timeout=60)
        report["runtime_schema_sql_probe"] = True
        with (candidate / "candidate.log").open("wb") as log:
            process = subprocess.Popen([str(backend / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1",
                                        "--port", "18013", "--no-access-log"], cwd=backend, env=runtime,
                                       stdout=log, stderr=log, user="course-management", group="course-management")
            ready("http://127.0.0.1:18013/health/ready")
            process.terminate()
            process.wait(timeout=15)
            process = None
        text = old_config.decode()
        for key, value in flags.items():
            text = re.sub(rf"(?m)^{key}=.*$", f"{key}={value}", text) if re.search(
                rf"(?m)^{key}=", text) else text.rstrip() + f"\n{key}={value}\n"
        pending = config.with_name(config.name + ".campus-pending")
        pending.write_text(text)
        pending.chmod(0o600)
        os.replace(pending, config)
        switch(ROOT / "current", candidate)
        switched = True
        switch(ROOT / "admin-web/current", web)
        subprocess.run(["systemctl", "start", "course-management"], check=True)
        stopped = False
        ready("http://127.0.0.1:8011/health/ready")
        ready("https://course.zsitai.xyz/health/ready")
        with urllib.request.urlopen("http://127.0.0.1:8011/openapi.json") as response:
            paths = json.load(response)["paths"]
        assert "/api/v1/me/timetable/entries/{eid}" in paths and "/api/v1/me/academic-notices" in paths
        assert "/api/v1/statistics/school-summary" in paths
        assert "/api/v1/me/timetable/entries/{eid}/restore" in paths
        assert "/api/v1/schools/{sid}/time-templates" in paths
        assert counts() == before
        report.update(status="passed", business_counts_unchanged=True, added_tables=sorted(created))
    except Exception:
        if process:
            process.terminate()
            process.wait(timeout=15)
        config.write_bytes(old_config)
        config.chmod(0o600)
        if switched:
            switch(ROOT / "current", old)
            switch(ROOT / "admin-web/current", old_web)
        if stopped or switched:
            subprocess.run(["systemctl", "restart", "course-management"], check=True)
            ready("http://127.0.0.1:8011/health/ready")
        report.update(status="failed", application_rollback=True, additive_schema_retained=True)
        raise
    finally:
        (candidate / "CAMPUS_RELEASE.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
