"""Root-only isolated server rehearsal; never switches production release pointers.

Run with the existing release's Python. Candidate archive must contain backend/.
Creates its own database/account, tests upgrade and downgrade, and removes only
those explicitly named resources. Production credentials never leave the host.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values


def select_candidate_python(old: Path, backend: Path, runtime: str | None) -> Path:
    if (backend / "uv.lock").read_bytes() == (old / "backend/uv.lock").read_bytes():
        return old / "backend/.venv/bin/python"
    if runtime is None:
        raise RuntimeError("Dependency lock changed; build a separate environment first")
    python = Path(runtime).absolute()
    installed_lock = python.parents[2] / "uv.lock"
    if not python.is_file() or installed_lock.read_bytes() != (backend / "uv.lock").read_bytes():
        raise RuntimeError("Candidate runtime must match the archived dependency lock")
    return python


def main() -> None:
    archive = Path(sys.argv[1]).resolve()
    expected_hash = sys.argv[2].lower()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError("Candidate checksum mismatch")
    suffix = secrets.token_hex(6)
    database = f"campus_rehearsal_{suffix}_test"
    account = f"cm_test_{suffix}"
    root = Path("/opt/course-management/rehearsals") / suffix
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    container = "course-management-mysql"
    mysql = [
        "docker",
        "exec",
        "-i",
        container,
        "timeout",
        "20",
        "mysql",
        "--defaults-extra-file=/run/cm-root.cnf",
        "-N",
    ]

    def sql(statement: str) -> str:
        return subprocess.check_output(mysql, input=statement.encode()).decode().strip()

    old = Path("/opt/course-management/current").resolve()
    web = Path("/opt/course-management/admin-web/current").resolve()
    old_head = sql("SELECT version_num FROM course_management.alembic_version;")
    report = {
        "source_backend": str(old),
        "source_web": str(web),
        "source_head": old_head,
        "candidate_sha256": expected_hash,
        "production_switched": False,
        "checks": [],
    }
    password = secrets.token_hex(24)
    process = None
    created_db = created_user = False
    stage = "prepare"
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 18011))
        with tarfile.open(archive) as bundle:
            bundle.extractall(root, filter="data")
        backend = root / "backend"
        python = select_candidate_python(old, backend, sys.argv[3] if len(sys.argv) > 3 else None)
        candidate_heads = (
            subprocess.check_output([str(python), "-m", "alembic", "heads"], cwd=backend)
            .decode()
            .splitlines()
        )
        if len(candidate_heads) != 1:
            raise RuntimeError("Candidate must have exactly one migration head")
        candidate_head = candidate_heads[0].split()[0]
        report["candidate_head"] = candidate_head
        dump = subprocess.check_output(
            [
                "docker",
                "exec",
                container,
                "mysqldump",
                "--defaults-extra-file=/run/cm-root.cnf",
                "--single-transaction",
                "--quick",
                "--no-tablespaces",
                "--set-gtid-purged=OFF",
                "course_management",
            ]
        )
        backup = root / "database.sql.gz"
        backup.write_bytes(gzip.compress(dump))
        backup.chmod(0o600)
        sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;")
        created_db = True
        subprocess.run(mysql + [database], input=dump, check=True, stdout=subprocess.DEVNULL)

        def data_digest() -> str:
            data = subprocess.check_output(
                [
                    "docker",
                    "exec",
                    container,
                    "mysqldump",
                    "--defaults-extra-file=/run/cm-root.cnf",
                    "--single-transaction",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    "--no-create-info",
                    "--skip-comments",
                    "--skip-add-locks",
                    "--skip-disable-keys",
                    "--order-by-primary",
                    database,
                ]
            )
            return hashlib.sha256(data).hexdigest()

        before_data = data_digest()
        report["before_data_sha256"] = before_data
        sql(f"CREATE USER '{account}'@'%' IDENTIFIED BY '{password}';")
        created_user = True
        sql(f"GRANT ALL ON `{database}`.* TO '{account}'@'%';")
        env = dict(os.environ)
        env.update(
            {
                k: v
                for k, v in dotenv_values("/etc/course-management/backend.env").items()
                if v is not None
            }
        )
        env.update(
            DATABASE_URL=f"mysql+pymysql://{account}:{password}@127.0.0.1:13308/{database}?charset=utf8mb4",
            APP_ENV="test",
            CAMPUS_CONFIGURATION_ENABLED="true",
            WECHAT_LOGIN_ENABLED="false",
            SECRET_KEY=secrets.token_hex(32),
            FILE_LOCAL_STORAGE_DIR=str(root / "files"),
            DB_POOL_SIZE="1",
            DB_MAX_OVERFLOW="0",
        )

        def migrate(revision: str) -> None:
            command = "upgrade" if revision == "head" else "downgrade"
            subprocess.run(
                [str(python), "-m", "alembic", command, revision], cwd=backend, env=env, check=True
            )

        def serve(directory: Path, candidate: bool) -> None:
            nonlocal process
            log = (root / "server.log").open("ab")
            process = subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18011",
                    "--no-access-log",
                ],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=log,
            )
            log.close()
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("Rehearsal server exited; inspect private server.log")
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:18011/health/ready", timeout=2
                    ) as response:
                        assert json.load(response)["database"] == "up"
                    break
                except urllib.error.URLError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Rehearsal readiness timeout")
            if candidate:
                with urllib.request.urlopen(
                    "http://127.0.0.1:18011/openapi.json", timeout=5
                ) as response:
                    assert "/api/v1/me/workspaces" in json.load(response)["paths"]
                try:
                    urllib.request.urlopen("http://127.0.0.1:18011/api/v1/me/workspaces", timeout=5)
                    raise AssertionError("Anonymous configuration access accepted")
                except urllib.error.HTTPError as error:
                    assert error.code == 401
            process.terminate()
            process.wait(timeout=15)
            process = None

        stage = "upgrade"
        migrate("head")
        assert sql(f"SELECT version_num FROM `{database}`.alembic_version;") == candidate_head
        report["checks"].append("clone_upgrade")
        serve(backend, True)
        report["checks"].append("candidate_readiness_openapi_auth")
        stage = "downgrade"
        migrate(old_head)
        # A merge downgrade leaves the other branch head intact. Explicitly remove
        # only campus revisions; keep the already deployed single-review branch.
        remaining = sql(f"SELECT version_num FROM `{database}`.alembic_version;").splitlines()
        if old_head == "181729fc7239" and "f26a1013c002" in remaining:
            migrate("f26a1013c002@b2c3d4e5f6a7")
        assert sql(f"SELECT version_num FROM `{database}`.alembic_version;") == old_head
        stage = "table_count"
        assert sql(
            f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{database}';"
        ) == sql(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='course_management';"
        )
        stage = "old_release_ready"
        serve(old / "backend", False)
        stage = "legacy_digest"
        after_data = data_digest()
        report["after_data_sha256"] = after_data
        assert after_data == before_data, "Downgrade changed legacy data"
        report["checks"].append("downgrade_old_release_readiness")
        report["checks"].append("legacy_data_digest_preserved")
        assert Path("/opt/course-management/current").resolve() == old
        assert Path("/opt/course-management/admin-web/current").resolve() == web
        assert sql("SELECT version_num FROM course_management.alembic_version;") == old_head
        with urllib.request.urlopen("http://127.0.0.1:8011/health/ready", timeout=5) as response:
            assert json.load(response)["database"] == "up"
        report["checks"].append("production_unchanged_ready")
        report["status"] = "passed"
    except Exception as error:
        report["failed_at"] = stage
        report["error_type"] = type(error).__name__
        raise
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        if created_db:
            sql(f"DROP DATABASE `{database}`;")
        if created_user:
            try:
                sql(f"DROP USER '{account}'@'%';")
            except subprocess.CalledProcessError:
                report["test_user_cleanup_pending"] = account
        report["isolated_resources_removed"] = not bool(report.get("test_user_cleanup_pending"))
        (root / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({**report, "evidence_directory": str(root)}))


if __name__ == "__main__":
    main()
