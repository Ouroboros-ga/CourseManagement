"""Use a separate pinned MySQL process for the unified migration rehearsal.

Arguments: prepared release, backend archive digest, existing private SQL snapshot.
No production SQL writes, user creation or DDL. Removes only its own container.
"""
import gzip
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values


def main():
    release, digest, snapshot = sys.argv[1:]
    backend = Path(release) / "backend"
    old = Path("/opt/course-management/current").resolve()
    web = Path("/opt/course-management/admin-web/current").resolve()
    suffix = secrets.token_hex(6)
    root = Path("/opt/course-management/rehearsals") / ("unified-" + suffix)
    root.mkdir(mode=0o700)
    container = "cm_unified_rehearsal_" + suffix
    database = "cm_unified_rehearsal_test"
    password = secrets.token_hex(24)
    cnf = root / "mysql.cnf"
    cnf.write_text(f"[client]\nuser=root\npassword={password}\n")
    cnf.chmod(0o600)
    envfile = root / "mysql.env"
    envfile.write_text(f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_ROOT_HOST=%\nMYSQL_DATABASE={database}\n")
    envfile.chmod(0o600)
    report = {"source_backend": str(old), "source_web": str(web), "source_head": "181729fc7239",
              "candidate_head": "f26a1014m001", "candidate_sha256": digest,
              "production_switched": False, "production_ddl": False, "checks": []}
    created = False
    process = None
    log = (root / "server.log").open("wb")
    stage = "prepare"
    mysql = ["docker", "exec", "-i", container, "timeout", "--kill-after=5", "120",
             "mysql", "--defaults-extra-file=/run/cm-root.cnf", "-N", database]

    def sql(statement):
        return subprocess.check_output(mysql + ["-e", statement], timeout=130).decode().strip()

    def data_digest():
        content = subprocess.check_output([
            "docker", "exec", container, "timeout", "--kill-after=5", "120", "mysqldump",
            "--defaults-extra-file=/run/cm-root.cnf", "--no-create-info", "--skip-comments",
            "--skip-add-locks", "--skip-disable-keys", "--order-by-primary", "--no-tablespaces",
            "--set-gtid-purged=OFF", database,
        ], timeout=130)
        return hashlib.sha256(content).hexdigest()

    try:
        for port in (13309, 18011):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        image = subprocess.check_output([
            "docker", "inspect", "--format", "{{.Config.Image}}", "course-management-mysql"
        ]).decode().strip()
        subprocess.run([
            "docker", "run", "-d", "--name", container, "--memory=384m", "--cpus=0.5",
            "--env-file", str(envfile), "-v", f"{cnf}:/run/cm-root.cnf:ro",
            "-p", "127.0.0.1:13309:3306", image,
            "--innodb-buffer-pool-size=32M", "--performance-schema=OFF", "--max-connections=20",
            "--key-buffer-size=4M", "--temptable-max-ram=32M", "--skip-log-bin",
        ], check=True, stdout=subprocess.DEVNULL)
        created = True
        stage = "mysql_init"
        for _ in range(90):
            result = subprocess.run(mysql + ["-e", "SELECT 1"], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=130, check=False)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Isolated MySQL failed to initialize")
        stage = "restore_private_snapshot"
        subprocess.run(mysql, input=gzip.decompress(Path(snapshot).read_bytes()), check=True,
                       stdout=subprocess.DEVNULL, timeout=130)
        assert sql("SELECT version_num FROM alembic_version") == report["source_head"]
        before = data_digest()
        table_count = sql("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
        report["before_data_sha256"] = before
        env = dict(os.environ)
        env.update({k: str(v) for k, v in dotenv_values("/etc/course-management/backend.env").items()
                    if v is not None})
        env.update(DATABASE_URL=f"mysql+pymysql://root:{password}@127.0.0.1:13309/{database}",
                   APP_ENV="test", SECRET_KEY=secrets.token_hex(32), WECHAT_LOGIN_ENABLED="false",
                   CAMPUS_CONFIGURATION_ENABLED="false", CAMPUS_ACADEMIC_SCOPED_ENABLED="false",
                   DB_POOL_SIZE="1", DB_MAX_OVERFLOW="0")
        python = str(backend / ".venv/bin/python")

        def migrate(direction, revision):
            subprocess.run([python, "-m", "alembic", direction, revision], cwd=backend,
                           env=env, check=True, timeout=130)

        def serve(directory, interpreter):
            nonlocal process
            process = subprocess.Popen([str(interpreter), "-m", "uvicorn", "app.main:app",
                                        "--host", "127.0.0.1", "--port", "18011", "--no-access-log"],
                                       cwd=directory, env=env, stdout=log, stderr=log)
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError("Candidate startup failed")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18011/health/ready", timeout=2) as response:
                        assert json.load(response)["database"] == "up"
                    break
                except urllib.error.URLError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("Isolated readiness timeout")
            try:
                urllib.request.urlopen("http://127.0.0.1:18011/api/v1/me/attendance", timeout=3)
                raise AssertionError("Anonymous attendance unexpectedly readable")
            except urllib.error.HTTPError as error:
                assert error.code == 401
            process.terminate()
            process.wait(timeout=15)
            process = None

        stage = "upgrade"
        migrate("upgrade", "head")
        assert sql("SELECT version_num FROM alembic_version") == report["candidate_head"]
        report["checks"].append("clone_upgrade")
        stage = "candidate_ready"
        serve(backend, python)
        report["checks"].append("candidate_readiness_auth")
        stage = "branch_rollback"
        migrate("downgrade", report["source_head"])
        migrate("downgrade", "f26a1013c002@b2c3d4e5f6a7")
        assert sql("SELECT version_num FROM alembic_version") == report["source_head"]
        assert sql("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()") == table_count
        after = data_digest()
        report["after_data_sha256"] = after
        assert after == before, "Legacy data changed"
        stage = "old_release_ready"
        serve(old / "backend", old / "backend/.venv/bin/python")
        report["checks"].extend(["downgrade_old_release_readiness", "legacy_data_digest_preserved"])
        assert Path("/opt/course-management/current").resolve() == old
        assert Path("/opt/course-management/admin-web/current").resolve() == web
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", failed_at=stage, error_type=type(error).__name__)
        raise
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        if created:
            subprocess.run(["docker", "rm", "-fv", container], check=True, stdout=subprocess.DEVNULL)
        log.close()
        report["isolated_resources_removed"] = True
        (root / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({**report, "evidence_directory": str(root)}))


if __name__ == "__main__":
    main()
