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
    def lock_bytes(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    if runtime is None and lock_bytes(backend / "uv.lock") == lock_bytes(old / "backend/uv.lock"):
        return old / "backend/.venv/bin/python"
    if runtime is None:
        raise RuntimeError("Dependency lock changed; build a separate environment first")
    python = Path(runtime).absolute()
    installed_lock = python.parents[2] / "uv.lock"
    if not python.is_file() or lock_bytes(installed_lock) != lock_bytes(backend / "uv.lock"):
        raise RuntimeError("Candidate runtime must match the archived dependency lock")
    return python


def main() -> None:
    archive = Path(sys.argv[1]).resolve()
    expected_hash = sys.argv[2].lower()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError("Candidate checksum mismatch")
    suffix = secrets.token_hex(6)
    database = f"campus_rehearsal_{suffix}_test"
    business_database = f"campus_business_{suffix}_test"
    account = f"cm_test_{suffix}"
    root = Path("/opt/course-management/rehearsals") / suffix
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    container = "course-management-mysql"
    mysql = [
        "docker",
        "exec",
        container,
        "timeout",
        "360",
        "mysql",
        "--defaults-extra-file=/run/cm-root.cnf",
        "--connect-timeout=10",
        "--init-command=SET SESSION lock_wait_timeout=15,innodb_lock_wait_timeout=15",
        "-N",
    ]

    def sql(statement: str) -> str:
        return subprocess.check_output(mysql + ["-e", statement], timeout=30).decode().strip()

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
    created_db = created_user = created_business_db = False
    import_path = f"/tmp/cm_candidate_import_{suffix}.sql"
    copied_import = False
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
        stage = "backup_and_clone"
        previous_snapshot = os.environ.get("CAMPUS_REHEARSAL_SNAPSHOT")
        if previous_snapshot:
            snapshot_path = Path(previous_snapshot).resolve()
            assert snapshot_path.is_relative_to(Path("/opt/course-management/rehearsals"))
            assert snapshot_path.name == "database.sql.gz"
            dump = gzip.decompress(snapshot_path.read_bytes())
            report["snapshot_sha256"] = hashlib.sha256(dump).hexdigest()
        else:
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
                , timeout=180
            )
        backup = root / "database.sql.gz"
        backup.write_bytes(gzip.compress(dump))
        backup.chmod(0o600)
        sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;")
        created_db = True
        # docker exec stdin can remain open across clients; mysql SOURCE provides a
        # bounded, closed-file restore without putting SQL or credentials on stdout.
        import_file = root / "restore.sql"
        import_file.write_bytes(dump)
        import_file.chmod(0o600)
        subprocess.run(["docker", "cp", str(import_file), f"{container}:{import_path}"],
                       check=True, timeout=30)
        copied_import = True
        stage = "restore_clone"
        print(json.dumps({"stage": stage, "test_database": database}), flush=True)
        subprocess.run(mysql + [database, "-e", f"source {import_path}"],
                       check=True, stdout=subprocess.DEVNULL, timeout=380)
        if sql(f"SELECT version_num FROM `{database}`.alembic_version;") != old_head:
            raise RuntimeError("Private snapshot migration does not match the live source baseline")

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
        stage = "isolated_mysql_business_regressions"
        sql(f"CREATE DATABASE `{business_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;")
        created_business_db = True
        sql(f"GRANT ALL ON `{business_database}`.* TO '{account}'@'%';")
        business_env = dict(env)
        business_env["CAMPUS_TEST_DATABASE_URL"] = (
            f"mysql+pymysql://{account}:{password}@127.0.0.1:13308/{business_database}?charset=utf8mb4"
        )
        modules = [
            "test_scoped_authorization_lifecycle", "test_scoped_academic_writes",
            "test_scoped_temporal_students", "test_scoped_importer",
            "test_college_time", "test_group_business", "test_group_member_impact",
            "test_group_sampling_business", "test_scoped_inspection_management",
            "test_group_mysql_execution",
            "test_scoped_audit", "test_scoped_qualification_export",
            "test_group_candidates", "test_configuration_future_impact",
            "test_group_warning_delivery", "test_group_eligibility_index", "test_scoped_binding_management",
            "test_scoped_semester_reset", "test_scoped_elective_batch", "test_college_deadlines",
            "test_group_task_restore", "test_scoped_smart_sample", "test_scoped_identity_queries",
            "test_scoped_handoff_tasks", "test_group_submission",
            "test_academic_publication", "test_personal_timetable", "test_publication_college_time",
        ]
        selected = os.environ.get("CAMPUS_REHEARSAL_TEST_MODULES")
        if selected:
            requested = selected.split(",")
            if not requested or not set(requested).issubset(modules):
                raise RuntimeError("Requested tests are outside the bounded acceptance list")
            modules = requested
        report["mysql_business_modules"] = modules
        business_log = root / "mysql-business-tests.log"
        with business_log.open("wb") as output:
            result = subprocess.run(
                [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 *[f"tests/unit/{name}.py" for name in modules]],
                cwd=backend, env=business_env, stdout=output, stderr=subprocess.STDOUT,
                timeout=480,
            )
        report["mysql_business_exit_code"] = result.returncode
        report["mysql_business_summary"] = business_log.read_text(errors="replace").splitlines()[-1:]
        if result.returncode:
            raise RuntimeError("Isolated MySQL business regression failed; inspect private host log")
        report["checks"].append("isolated_mysql_business_regressions")
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
        if copied_import:
            assert import_path == f"/tmp/cm_candidate_import_{suffix}.sql"
            subprocess.run(["docker", "exec", container, "rm", "--", import_path],
                           check=True, timeout=30)
        if created_db:
            sql(f"DROP DATABASE `{database}`;")
        if created_business_db:
            sql(f"DROP DATABASE `{business_database}`;")
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
