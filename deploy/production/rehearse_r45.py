"""Run focused candidate tests on the server's MySQL in a disposable schema.

Execute with the deployed Python, passing an unpacked candidate backend path.
Credentials stay in memory; this script never changes the running release.
"""

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path


def main():
    candidate = Path(sys.argv[1]).resolve()
    if not (candidate / "pyproject.toml").is_file() or not str(candidate).startswith(
        "/opt/course-management/rehearsals/"
    ):
        raise RuntimeError(
            "Candidate must be an unpacked backend in the rehearsals directory"
        )
    token = secrets.token_hex(5)
    database, user = f"cm_r45_{token}_test", f"cm_r45_{token}"
    if not re.fullmatch(r"cm_r45_[0-9a-f]{10}_test", database):
        raise RuntimeError("Invalid disposable schema name")
    password = secrets.token_hex(24)

    def sql(statement):
        return subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "course-management-mysql",
                "mysql",
                "--defaults-extra-file=/run/cm-root.cnf",
                "-N",
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=True,
        ).stdout

    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    production = make_url(
        dotenv_values("/etc/course-management/backend.env")["DATABASE_URL"]
    )
    url = production.set(username=user, password=password, database=database)
    env = {
        **os.environ,
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "CAMPUS_TEST_DATABASE_URL": url.render_as_string(hide_password=False),
        "PYTHONPATH": str(candidate),
    }
    report = {
        "schema": database,
        "production_touched": False,
        "candidate": str(candidate),
    }
    bundle = os.environ.get("CAMPUS_REHEARSAL_BUNDLE")
    if bundle:
        bundle_path = Path(bundle).resolve()
        if not str(bundle_path).startswith("/opt/course-management/rehearsals/"):
            raise RuntimeError(
                "Rehearsal bundle must be inside the rehearsal directory"
            )
        report["source_bundle_sha256"] = hashlib.sha256(
            bundle_path.read_bytes()
        ).hexdigest()
    created = False
    try:
        sql(
            f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\n"
            f"CREATE USER '{user}'@'%' IDENTIFIED BY '{password}';\n"
            f"GRANT ALL ON `{database}`.* TO '{user}'@'%';"
        )
        created = True
        arguments = sys.argv[2:]
        migration = "--migration" in arguments
        tests = [argument for argument in arguments if argument != "--migration"] or [
            "tests/unit/test_school_time_templates.py",
            "tests/unit/test_group_handover.py",
        ]
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", *tests],
            cwd=candidate,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        # Test output is private evidence beside the candidate; no environment dump.
        log = (run.stdout + run.stderr).replace(password, "[redacted]")
        (candidate.parent / "focused-tests.log").write_text(log)
        report.update(test_exit_code=run.returncode, tests=tests, output=log[-18000:])
        if migration and run.returncode == 0:
            # A single consistent production snapshot is read-only at the source;
            # all upgrades, downgrades and hashes operate on the disposable clone.
            dump = subprocess.run(
                [
                    "docker",
                    "exec",
                    "course-management-mysql",
                    "mysqldump",
                    "--defaults-extra-file=/run/cm-root.cnf",
                    "--single-transaction",
                    "--skip-lock-tables",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    production.database,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            ).stdout
            if re.search(r"^(USE |CREATE DATABASE|DROP DATABASE)", dump, re.MULTILINE):
                raise RuntimeError("Snapshot contains schema-switching statements")
            sql(
                f"DROP DATABASE `{database}`; CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
            )
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "course-management-mysql",
                    "mysql",
                    "--defaults-extra-file=/run/cm-root.cnf",
                    database,
                ],
                input=dump,
                text=True,
                capture_output=True,
                check=True,
                timeout=120,
            )
            from sqlalchemy import create_engine, inspect
            from sqlalchemy import text as sql_text

            engine = create_engine(url)
            with engine.connect() as connection:
                original_tables = inspect(connection).get_table_names()
                columns = {
                    table: [c["name"] for c in inspect(connection).get_columns(table)]
                    for table in original_tables
                    if table != "alembic_version"
                }
                baseline = connection.execute(
                    sql_text("SELECT version_num FROM alembic_version")
                ).scalar_one()

            def original_digest():
                hashes = {}
                with engine.connect() as connection:
                    for table, names in columns.items():
                        values = list(
                            connection.execute(
                                sql_text(
                                    "SELECT "
                                    + ",".join(f"`{name}`" for name in names)
                                    + f" FROM `{table}`"
                                )
                            )
                        )
                        encoded = sorted(
                            json.dumps(list(row), default=str, ensure_ascii=False)
                            for row in values
                        )
                        hashes[table] = {
                            "count": len(values),
                            "sha256": hashlib.sha256(
                                "\n".join(encoded).encode()
                            ).hexdigest(),
                        }
                return hashes

            before = original_digest()
            stages = []
            for command in (
                ["upgrade", "head"],
                ["downgrade", baseline],
                ["upgrade", "head"],
            ):
                result = subprocess.run(
                    [sys.executable, "-m", "alembic", *command],
                    cwd=candidate,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                stages.append({"command": command, "exit_code": result.returncode})
                if result.returncode:
                    (candidate.parent / "migration.log").write_text(
                        (result.stdout + result.stderr).replace(password, "[redacted]")
                    )
                    raise RuntimeError(
                        "Clone migration failed; see private migration.log"
                    )
            after = original_digest()
            report["migration"] = {
                "baseline": baseline,
                "stages": stages,
                "original_table_count": len(before),
                "original_data_unchanged": before == after,
            }
            engine.dispose()
            if before != after:
                raise RuntimeError("Original data changed during clone migration")
    finally:
        if created:
            sql(f"DROP DATABASE `{database}`; DROP USER '{user}'@'%';")
            report["test_schema_removed"] = True
        (candidate.parent / "R45_MYSQL_RESULT.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    print(json.dumps(report, ensure_ascii=False))
    return report.get("test_exit_code", 1)


if __name__ == "__main__":
    sys.exit(main())
