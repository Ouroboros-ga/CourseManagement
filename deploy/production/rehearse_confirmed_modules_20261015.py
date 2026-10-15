"""One incremental migration preflight in a disposable production-clone schema."""
import configparser
import gzip
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url


def main():
    release, digest, backup = sys.argv[1:]
    backend = Path(release) / "backend"
    suffix = secrets.token_hex(5)
    database = f"cm_confirmed_{suffix}_test"
    assert re.fullmatch(r"cm_confirmed_[0-9a-f]{10}_test", database)
    output = Path(release) / "REHEARSAL.json"
    mysql = ["docker", "exec", "-i", "course-management-mysql", "timeout", "--kill-after=5", "110", "mysql", "--defaults-extra-file=/run/cm-root.cnf", "-N"]
    def sql(statement):
        return subprocess.check_output(mysql + ["-e", statement], timeout=60).decode().strip()
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(subprocess.check_output(["docker", "exec", "course-management-mysql", "cat", "/run/cm-root.cnf"]).decode())
    password = config["client"]["password"].strip('"').strip("'")
    environment = {**os.environ, **{k: v for k,v in dotenv_values("/etc/course-management/backend.env").items() if v is not None}}
    server_url = make_url(environment["DATABASE_URL"])
    environment.update(DATABASE_URL=URL.create("mysql+pymysql", username="root", password=password,
        host=server_url.host or "127.0.0.1", port=server_url.port or 3306, database=database).render_as_string(hide_password=False),
        PYTHONPATH=str(backend), APP_ENV="test", WECHAT_LOGIN_ENABLED="false")
    python = "/opt/course-management/current/backend/.venv/bin/python"
    report = {"candidate_head": "f26a1015h001", "candidate_sha256": digest, "status": "running"}
    created = False
    process = None
    try:
        assert not sql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{database}'")
        sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        created = True
        print(json.dumps({"stage": "restore_clone"}), flush=True)
        dump = gzip.decompress(Path(backup).read_bytes())
        assert not re.search(rb"(?im)^USE\s+", dump)
        subprocess.run(mysql + [database], input=dump, check=True, timeout=120, stdout=subprocess.DEVNULL)
        initial = sql(f"SELECT version_num FROM `{database}`.alembic_version")
        assert initial == "f26a1015e001"
        def migrate(direction, target):
            subprocess.run([python, "-m", "alembic", direction, target], cwd=backend, env=environment, check=True, timeout=120)
        print(json.dumps({"stage": "migration_up"}), flush=True)
        migrate("upgrade", "head")
        assert sql(f"SELECT version_num FROM `{database}`.alembic_version") == report["candidate_head"]
        with (Path(release) / "rehearsal-server.log").open("wb") as log:
            process = subprocess.Popen([python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18014", "--no-access-log"], cwd=backend, env=environment, stdout=log, stderr=log)
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("Candidate startup failed; inspect private server log")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18014/health/ready", timeout=2) as response:
                        assert json.load(response)["database"] == "up"
                    break
                except OSError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("Candidate readiness timeout")
            process.terminate(); process.wait(timeout=15); process = None
        # New additive identities/facts intentionally prohibit destructive downgrade.
        # Verify legacy-compatible JSON defaults instead; production app rollback
        # retains these additive tables/columns.
        columns = sql(f"SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{database}' AND TABLE_NAME='personal_timetable' AND COLUMN_NAME IN ('deleted_entries','occurrence_exceptions') AND COLUMN_DEFAULT IS NOT NULL")
        assert columns == "2"
        report.update(status="passed", clone_upgrade=True, candidate_ready=True,
                      legacy_insert_defaults=True, application_rollback_retains_schema=True)
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        if process:
            process.terminate(); process.wait(timeout=15)
        if created:
            sql(f"DROP DATABASE `{database}`")
        report["test_schema_removed"] = created
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
