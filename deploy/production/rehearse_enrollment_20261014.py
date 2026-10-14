"""Clone production snapshot into a separate MySQL container, never alter live SQL.

Arguments: candidate release directory, source archive digest, private SQL .gz snapshot.
Keeps backups private; prints only hashes, counts and status.
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
from pathlib import Path

from dotenv import dotenv_values


def main():
    release, digest, snapshot = sys.argv[1:]
    candidate = Path(release).resolve()
    assert candidate.parent == Path("/opt/course-management/releases")
    assert candidate.name.startswith("20261014-enrollment-")
    old = Path("/opt/course-management/current").resolve()
    suffix = secrets.token_hex(6)
    root = Path("/opt/course-management/rehearsals") / ("enrollment-" + suffix)
    root.mkdir(mode=0o700)
    container = "cm_enrollment_rehearsal_" + suffix
    database = "cm_enrollment_rehearsal_test"
    password = secrets.token_hex(24)
    cnf = root / "mysql.cnf"
    cnf.write_text(f"[client]\nuser=root\npassword={password}\n")
    cnf.chmod(0o600)
    envfile = root / "mysql.env"
    envfile.write_text(
        f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_ROOT_HOST=%\nMYSQL_DATABASE={database}\n"
    )
    envfile.chmod(0o600)
    mysql = [
        "docker",
        "exec",
        "-i",
        container,
        "mysql",
        "--defaults-extra-file=/run/cm-root.cnf",
        "-N",
        database,
    ]

    def sql(query):
        return (
            subprocess.check_output(mysql + ["-e", query], timeout=120).decode().strip()
        )

    def facts():
        return {
            name: hashlib.sha256(sql(query).encode()).hexdigest()
            for name, query in {
                "students": "SELECT id,student_no,name,administrative_class_id,status FROM student ORDER BY id",
                "accounts": "SELECT id,username,password_hash,student_id,status FROM user_account ORDER BY id",
                "rosters": "SELECT task_id,roster_version,student_id,student_no,name,class_name_snapshot,grade_year_snapshot FROM task_roster_member ORDER BY task_id,roster_version,student_id",
                "attendance": "SELECT id,task_id,student_id,current_version,effective_type FROM attendance_record ORDER BY id",
                "bindings": "SELECT user_id,appid,openid FROM wechat_identity ORDER BY id",
            }.items()
        }

    env = dict(os.environ)
    env.update(
        {
            k: str(v)
            for k, v in dotenv_values("/etc/course-management/backend.env").items()
            if v is not None
        }
    )
    env.update(
        DATABASE_URL=f"mysql+pymysql://root:{password}@127.0.0.1:13309/{database}?charset=utf8mb4",
        TEST_DATABASE_URL=f"mysql+pymysql://root:{password}@127.0.0.1:13309/{database}?charset=utf8mb4",
        APP_ENV="test",
        SECRET_KEY=secrets.token_hex(32),
        STATIC_KEY=secrets.token_hex(32),
        JWT_SECRET_KEY=secrets.token_hex(32),
        CAMPUS_CONFIGURATION_ENABLED="true",
        CAMPUS_ACADEMIC_SCOPED_ENABLED="true",
        WECHAT_LOGIN_ENABLED="false",
        FILE_STORAGE_BACKEND="local",
        PYTHONPATH=str(candidate / "backend"),
    )
    python = str(candidate / "backend/.venv/bin/python")
    report = {
        "candidate_sha256": digest,
        "production_switched": False,
        "production_ddl": False,
        "checks": [],
    }
    created = False
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 13309))
        image = (
            subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.Config.Image}}",
                    "course-management-mysql",
                ]
            )
            .decode()
            .strip()
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "--memory=384m",
                "--cpus=0.5",
                "--env-file",
                str(envfile),
                "-v",
                f"{cnf}:/run/cm-root.cnf:ro",
                "-p",
                "127.0.0.1:13309:3306",
                image,
                "--innodb-buffer-pool-size=32M",
                "--performance-schema=OFF",
                "--max-connections=20",
                "--skip-log-bin",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        created = True
        for _ in range(90):
            if (
                subprocess.run(
                    mysql + ["-e", "SELECT 1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Isolated MySQL readiness timeout")
        subprocess.run(
            mysql,
            input=gzip.decompress(Path(snapshot).read_bytes()),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        assert sql("SELECT version_num FROM alembic_version") == "f26a1014m001"
        before = facts()
        subprocess.run(
            [python, "-m", "alembic", "upgrade", "head"],
            cwd=candidate / "backend",
            env=env,
            check=True,
        )
        assert sql("SELECT version_num FROM alembic_version") == "f26a1014e001"
        assert facts() == before
        report["checks"].append(
            "mysql_upgrade_preserves_identity_bindings_rosters_attendance"
        )
        subprocess.run(
            [python, "-m", "alembic", "downgrade", "f26a1014m001"],
            cwd=candidate / "backend",
            env=env,
            check=True,
        )
        assert facts() == before
        report["checks"].append("mysql_downgrade_preserves_original_facts")
        subprocess.run(
            [python, "-m", "alembic", "upgrade", "head"],
            cwd=candidate / "backend",
            env=env,
            check=True,
        )
        subprocess.run(
            [python, "/tmp/cm-initialize-enrollment.py"],
            cwd=candidate / "backend",
            env=env,
            check=True,
        )
        assert facts() == before
        report["checks"].append("confirmed_initialization_preserves_business_facts")
        subprocess.run(
            [python, "/tmp/cm-verify-enrollment.py", "clone"],
            cwd=candidate / "backend",
            env=env,
            check=True,
        )
        report["checks"].append("college_scope_platform_flag_and_lifecycle_acceptance")
        assert Path("/opt/course-management/current").resolve() == old
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        if created:
            subprocess.run(
                ["docker", "rm", "-fv", container],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        report["isolated_resources_removed"] = True
        (root / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({**report, "evidence_directory": str(root)}))


if __name__ == "__main__":
    main()
