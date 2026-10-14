"""Publish locally committed e001 source after isolated MySQL rehearsal.

Run with the current Linux venv. No student/class/account deletion. A failed
release restores app/config pointers and leaves additive schema intact.
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
NEW_HEAD = "f26a1014e001"
OLD_HEAD = "f26a1014m001"
TABLES = (
    "course_participation",
    "student_enrollment",
    "enrollment_change",
    "student_data_plan",
    "student_manager_appointment",
    "teacher_college_binding",
    "teaching_class_audience",
    "task_schedule_source",
)
FLAGS = ("CAMPUS_CONFIGURATION_ENABLED", "CAMPUS_ACADEMIC_SCOPED_ENABLED")


def sql(statement):
    return (
        subprocess.check_output(
            [
                "docker",
                "exec",
                "-i",
                "course-management-mysql",
                "mysql",
                "--defaults-extra-file=/run/cm-root.cnf",
                "-N",
            ],
            input=statement.encode(),
        )
        .decode()
        .strip()
    )


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
    temporary = pointer.with_name(pointer.name + ".enrollment-pending")
    assert not temporary.exists() and not temporary.is_symlink()
    temporary.symlink_to(destination)
    os.replace(temporary, pointer)


def env_values(path):
    return {k: str(v) for k, v in dotenv_values(path).items() if v is not None}


def counts():
    return {
        name: int(sql(f"SELECT COUNT(*) FROM course_management.`{name}`;"))
        for name in (
            "student",
            "user_account",
            "administrative_class",
            "wechat_identity",
            "task_roster_member",
            "attendance_record",
        )
    }


def main():
    candidate_path, web_path, rehearsal_path = map(Path, sys.argv[1:])
    candidate = candidate_path.resolve()
    assert candidate.parent == ROOT / "releases"
    assert candidate.name.startswith("20261014-enrollment-candidate-")
    manifest = json.loads((candidate / "SOURCE_MANIFEST.json").read_text())
    assert manifest["source_dirty"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_head"])
    rehearsal = json.loads(rehearsal_path.read_text())
    assert rehearsal["status"] == "passed"
    assert rehearsal["candidate_sha256"] == manifest["backend_sha256"]
    for name, digest in manifest["source_files"].items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == digest, (
            name
        )
    for name, digest in manifest["deployment_files"].items():
        assert (
            hashlib.sha256((Path("/tmp") / Path(name).name).read_bytes()).hexdigest()
            == digest
        )
    assert hashlib.sha256(web_path.read_bytes()).hexdigest() == manifest["web_sha256"]
    old, old_web = (ROOT / "current").resolve(), (ROOT / "admin-web/current").resolve()
    assert old.name == old_web.name == "20261014-unified"
    assert sql("SELECT version_num FROM course_management.alembic_version;") == OLD_HEAD
    before_counts = counts()
    assert before_counts["administrative_class"] == 41
    runtime_path = Path("/etc/course-management/backend.env")
    old_config = runtime_path.read_bytes()
    runtime_env = {**os.environ, **env_values(runtime_path)}
    runtime_url = make_url(runtime_env["DATABASE_URL"])
    assert runtime_url.database == "course_management"
    user = runtime_url.username
    assert user and re.fullmatch(r"[A-Za-z0-9_]+", user)
    assert sql(f"SELECT Host FROM mysql.user WHERE User='{user}';").splitlines() == [
        "%"
    ]
    migration_env = {
        **runtime_env,
        **env_values("/etc/course-management/migration.env"),
    }
    assert make_url(migration_env["DATABASE_URL"]).database == "course_management"
    runtime_env.update({flag: "true" for flag in FLAGS})
    runtime_env["PYTHONPATH"] = str(candidate / "backend")
    migration_env["PYTHONPATH"] = str(candidate / "backend")
    python = str(candidate / "backend/.venv/bin/python")
    new_web = ROOT / "admin-web/releases" / candidate.name
    new_web.mkdir(mode=0o755, exist_ok=False)
    with tarfile.open(web_path) as bundle:
        bundle.extractall(new_web, filter="data")
    for source in (old_web / "assets").iterdir():
        destination = new_web / "assets" / source.name
        if source.is_file() and not destination.exists():
            destination.write_bytes(source.read_bytes())
    for path in new_web.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    report = {
        "source_head": manifest["source_head"],
        "migration_head": NEW_HEAD,
        "backend_release": str(candidate),
        "web_release": str(new_web),
        "previous_backend": str(old),
        "previous_web": str(old_web),
        "backend_sha256": manifest["backend_sha256"],
        "web_sha256": manifest["web_sha256"],
        "rehearsal": str(rehearsal_path),
        "college_flags_enabled": True,
        "preserved_counts": before_counts,
        "checks": [],
    }
    stopped = switched = config_changed = False
    process = None
    logfile = (candidate / "candidate.log").open("wb")
    try:
        subprocess.run(["systemctl", "stop", "course-management"], check=True)
        stopped = True
        assert (ROOT / "current").resolve() == old
        # App is stopped: this snapshot is the actual rollback boundary for DDL/init.
        backup = Path(
            subprocess.check_output(["bash", str(ROOT / "backup.sh")]).decode().strip()
        )
        assert backup.parent == Path("/var/backups/course-management")
        subprocess.run(
            ["sha256sum", "--check", "SHA256SUMS"],
            cwd=backup,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        report["backup"] = str(backup)
        print(
            json.dumps({"stage": "backup_verified", "backup": str(backup)}), flush=True
        )
        subprocess.run(
            [python, "-m", "alembic", "upgrade", NEW_HEAD],
            cwd=candidate / "backend",
            env=migration_env,
            check=True,
        )
        assert (
            sql("SELECT version_num FROM course_management.alembic_version;")
            == NEW_HEAD
        )
        for table in TABLES:
            sql(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON course_management.`{table}` TO '{user}'@'%';"
            )
        subprocess.run(
            [python, "/tmp/initialize_enrollment_20261014.py"],
            cwd=candidate / "backend",
            env=migration_env,
            check=True,
        )
        assert counts() == before_counts, "Business row count changed unexpectedly"
        subprocess.run(
            [python, "/tmp/verify_enrollment_20261014.py"],
            cwd=candidate / "backend",
            env=runtime_env,
            check=True,
        )
        report["checks"].append(
            "migration_initialization_runtime_grants_no_business_deletion"
        )
        process = subprocess.Popen(
            [
                python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18011",
                "--no-access-log",
            ],
            cwd=candidate / "backend",
            env=runtime_env,
            stdout=logfile,
            stderr=logfile,
            user="course-management",
            group="course-management",
        )
        ready("http://127.0.0.1:18011/health/ready")
        process.terminate()
        process.wait(timeout=15)
        process = None
        # Change only the two public feature flags. Preserve every secret/config value.
        config = old_config.decode()
        for flag in FLAGS:
            expression = rf"(?m)^\s*{flag}\s*=.*$"
            config = (
                re.sub(expression, flag + "=true", config)
                if re.search(expression, config)
                else config + "\n" + flag + "=true\n"
            )
        runtime_path.write_text(config)
        config_changed = True
        switch(ROOT / "current", candidate)
        switched = True
        switch(ROOT / "admin-web/current", new_web)
        subprocess.run(["systemctl", "start", "course-management"], check=True)
        stopped = False
        ready("http://127.0.0.1:8011/health/ready")
        ready("https://course.zsitai.xyz/health/ready")
        with urllib.request.urlopen(
            "https://course.zsitai.xyz/", timeout=10
        ) as response:
            assert response.read() == (new_web / "index.html").read_bytes()
        subprocess.run(
            [python, "/tmp/verify_enrollment_20261014.py"],
            cwd=candidate / "backend",
            env=runtime_env,
            check=True,
        )
        assert counts() == before_counts
        report["checks"].append(
            "candidate_and_live_public_readiness_web_source_and_readonly_acceptance"
        )
        report["passed"] = True
        (candidate / "ENROLLMENT_RELEASE.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    except Exception:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
            process = None
        if config_changed:
            runtime_path.write_bytes(old_config)
        if switched:
            switch(ROOT / "current", old)
            switch(ROOT / "admin-web/current", old_web)
        if stopped or switched:
            subprocess.run(["systemctl", "restart", "course-management"], check=True)
            ready("http://127.0.0.1:8011/health/ready")
        report.update(
            passed=False,
            application_restored=stopped or switched,
            schema_rollback=False,
        )
        (candidate / "ENROLLMENT_RELEASE.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
        raise
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        logfile.close()


if __name__ == "__main__":
    main()
