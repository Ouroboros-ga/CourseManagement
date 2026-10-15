"""Two-college HTTP acceptance on the disposable server MySQL, without service mocks."""

import base64
import json
import os
import socket
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from app.core.database import utcnow
from app.core.security import hash_password
from app.modules.academic.enrollment_models import TeacherCollegeBinding
from app.modules.academic.models import Student
from app.modules.identity.models import Role, UserAccount
from app.modules.identity.seed import sync_registry
from sqlalchemy import select, text

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_importer import sheet


@pytest.fixture(name="campus")
def fixture():
    if not os.environ.get("CAMPUS_TEST_DATABASE_URL"):
        pytest.skip("R6 requires the explicitly isolated server MySQL")
    yield from campus_fixture.__wrapped__()


def test_two_college_real_http_lifecycle(campus, tmp_path):
    _, db, admin, teacher, a, b = campus
    sync_registry(db)
    password = "R6-Acceptance-Only-42!"
    for uid, username in ((admin.id, "r6admin"), (teacher.id, "r6teacherA")):
        user = db.get(UserAccount, uid)
        user.username, user.password_hash = username, hash_password(password)
    roles = {r.code: r for r in db.scalars(select(Role))}
    db.get(UserAccount, teacher.id).roles = [roles["TEACHER_ADMIN"]]
    db.add(TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"])))
    teacher_b = UserAccount(
        username="r6teacherB",
        password_hash=hash_password(password),
        display_name="R6 B teacher",
        roles=[roles["TEACHER_ADMIN"]],
    )
    db.add(teacher_b)
    db.flush()
    db.add(TeacherCollegeBinding(user_id=teacher_b.id, college_id=int(b["id"])))
    db.commit()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "APP_ENV": "dev",
        "COOKIE_SECURE": "false",
        "CSRF_ALLOWED_ORIGINS": "http://127.0.0.1:18147",
        "SECRET_KEY": "r6-ephemeral-acceptance-secret-should-never-be-production",
        "CAMPUS_CONFIGURATION_ENABLED": "true",
        "CAMPUS_ACADEMIC_SCOPED_ENABLED": "true",
        "CAMPUS_BUSINESS_SCOPED_ENABLED": "true",
        "CAMPUS_SCHEDULING_ENABLED": "true",
        "ACADEMIC_PUBLICATION_ENABLED": "true",
        "FILE_STORAGE_BACKEND": "local",
        "FILE_LOCAL_STORAGE_DIR": str(tmp_path / "files"),
        "CM_DEV_ALLOW_EARLY_SUBMISSION": "0",
    }
    log = (tmp_path / "http-service.log").open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        stdout=log,
        stderr=log,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
            for _ in range(60):
                try:
                    if client.get("/health/ready").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None, (tmp_path / "http-service.log").read_text()
                time.sleep(0.2)
            else:
                pytest.fail("Isolated candidate HTTP server not ready")

            def call(method, path, token=None, expected=200, **kwargs):
                print("R6 HTTP", method, path, flush=True)
                try:
                    response = client.request(
                        method,
                        "/api/v1" + path,
                        headers={"Authorization": f"Bearer {token}"} if token else {},
                        **kwargs,
                    )
                except httpx.ReadTimeout:
                    # This user can only see its own disposable-schema connections.
                    with db.get_bind().connect() as diagnostic:
                        print(
                            "R6 DB wait",
                            diagnostic.execute(text("SHOW FULL PROCESSLIST")).all(),
                            flush=True,
                        )
                    raise
                assert response.status_code == expected, (method, path, response.text)
                return response.json().get("data") if expected == 200 else response

            def login(username):
                return call(
                    "POST", "/auth/web/login", json={"username": username, "password": password}
                )["access_token"]

            root = login("r6admin")
            tokens = [login("r6teacherA"), login("r6teacherB")]
            today = (utcnow() + timedelta(hours=8)).date()
            monday = today - timedelta(days=today.weekday())
            semester = call(
                "POST",
                "/academic/semesters",
                root,
                json={
                    "code": "R6",
                    "name": "R6 disposable semester",
                    "start_date": str(monday),
                    "end_date": str(monday + timedelta(days=90)),
                    "first_monday": str(monday),
                    "total_weeks": 13,
                },
            )
            sid = semester["id"]
            previous = call(
                "POST",
                "/academic/semesters",
                root,
                json={
                    "code": "R6PREV",
                    "name": "R6 prior",
                    "start_date": str(monday - timedelta(days=120)),
                    "end_date": str(monday - timedelta(days=30)),
                    "first_monday": str(monday - timedelta(days=126)),
                    "total_weeks": 15,
                },
            )
            views = []

            def import_rows(prefix, token, target, rows, **fields):
                draft = call(
                    "POST",
                    prefix + "/imports",
                    token,
                    data={"target": target, "replace": "false", **fields},
                    files={
                        "file": (
                            "r6.xlsx",
                            sheet(rows),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                )
                ids = [draft["id"]]
                plan = call(
                    "POST",
                    prefix + "/imports/confirmation-set/preview",
                    token,
                    json={"batch_ids": ids},
                )
                assert plan["can_confirm"], plan
                body = {"batch_ids": ids, "revision": plan["revision"]}
                result = call(
                    "POST", prefix + "/imports/confirmation-set/confirm", token, json=body
                )
                assert result == call(
                    "POST", prefix + "/imports/confirmation-set/confirm", token, json=body
                )

            for index, (college, token) in enumerate(zip((a, b), tokens, strict=True)):
                prefix = "/colleges/" + college["id"]
                ac = call(
                    "POST",
                    prefix + "/academic/administrative-classes",
                    token,
                    json={
                        "class_code": f"R6-{index}",
                        "class_name": f"R6 class {index}",
                        "grade_year": 2026,
                    },
                )
                learner = Student(
                    student_no=f"000R6{index}S",
                    name=f"R6 student {index}",
                    administrative_class_id=int(ac["id"]),
                )
                volunteer = Student(
                    student_no=f"000R6{index}V",
                    name=f"R6 volunteer {index}",
                    administrative_class_id=int(ac["id"]),
                )
                db.add_all([learner, volunteer])
                db.flush()
                users = []
                for suffix, student in (("s", learner), ("v", volunteer)):
                    user = UserAccount(
                        username=f"r6{index}{suffix}",
                        display_name=student.name,
                        password_hash=hash_password(password),
                        student_id=student.id,
                        roles=[roles["STUDENT"]] + ([roles["VOLUNTEER"]] if suffix == "v" else []),
                    )
                    db.add(user)
                    users.append(user)
                db.commit()
                time_body = {
                    "effective_from": str(monday),
                    "periods": [{"period_no": 1, "start_time": "07:00", "end_time": "07:40"}],
                }
                tp = prefix + f"/academic/semesters/{sid}/time-versions"
                preview = call("POST", tp + "/preview", token, json=time_body)
                call(
                    "POST",
                    tp + "/publish",
                    token,
                    json={**time_body, "revision": preview["revision"]},
                )
                import_rows(
                    prefix,
                    token,
                    "timetable",
                    [
                        [
                            "教学班码",
                            "课程代码",
                            "课程名称",
                            "星期",
                            "开始大节",
                            "结束大节",
                            "周次",
                            "上课地点",
                        ],
                        [
                            f"TC{index}",
                            "SAME-CODE",
                            "R6 shared course",
                            today.isoweekday(),
                            1,
                            1,
                            "1-2",
                            "R6-101",
                        ],
                    ],
                    semester_id=sid,
                )
                tc = call("GET", prefix + f"/academic/teaching-classes?semester_id={sid}", token)[
                    "items"
                ][0]
                import_rows(
                    prefix,
                    token,
                    "roster",
                    [["学号"], [learner.student_no]],
                    teaching_class_id=tc["id"],
                )
                import_rows(
                    prefix,
                    token,
                    "volunteer",
                    [["学号", "是否启用"], [volunteer.student_no, "是"]],
                    semester_id=sid,
                )
                kind = call("GET", prefix + "/course-types", token)[0]
                call(
                    "PUT",
                    prefix + f"/academic/teaching-classes/{tc['id']}/course-type",
                    token,
                    json={
                        "course_type_id": kind["id"],
                        "classification_revision": tc["classification_revision"],
                    },
                )
                group = call(
                    "POST",
                    prefix + "/volunteer-groups",
                    token,
                    json={"name": "R6 check group", "owner_user_id": str(users[1].id)},
                )
                gp = prefix + "/groups/" + group["id"]
                group = call(
                    "POST",
                    gp + "/configuration/publish",
                    token,
                    json={
                        "lock_version": group["lock_version"],
                        "course_type_ids": [kind["id"]],
                        "own_class_effect": "ALLOW",
                        "default_effect": "ALLOW",
                    },
                )
                call(
                    "PATCH",
                    gp,
                    token,
                    json={"lock_version": group["lock_version"], "status": "ACTIVE"},
                )
                call(
                    "POST",
                    gp + "/members",
                    token,
                    json={
                        "student_id": str(volunteer.id),
                        "semester_id": sid,
                        "effective_from": str(monday),
                        "effective_to": str(monday + timedelta(days=91)),
                    },
                )
                # Changing a remembered semester cannot filter the persistent class directory.
                assert (
                    call("GET", prefix + f"/academic/students?semester_id={previous['id']}", token)[
                        "total"
                    ]
                    == 2
                )
                views.append(
                    dict(
                        prefix=prefix,
                        token=token,
                        tid=tc["id"],
                        gp=gp,
                        ac=ac["id"],
                        student=learner,
                        student_token=login(f"r6{index}s"),
                        volunteer_token=login(f"r6{index}v"),
                        volunteer_user=users[1].id,
                    )
                )

            own, other = views
            for view in views:
                publication = view["prefix"] + f"/academic/semesters/{sid}"
                publication_preview = call(
                    "POST", publication + "/publication-preview", view["token"]
                )
                call(
                    "POST",
                    publication + "/publish",
                    view["token"],
                    json={"source_revision": publication_preview["source_revision"]},
                )
                official = call(
                    "GET", f"/me/timetable/official-source?semester_id={sid}", view["student_token"]
                )
                assert official["status"] == "AVAILABLE" and len(official["entries"]) == 1
                assert official["entries"][0]["course_name"] == "R6 shared course"
            identity = own["prefix"] + f"/academic/teaching-classes/{own['tid']}/shared-identity"
            candidates = call("GET", identity + "/candidates", own["token"])
            assert candidates
            link = {"target_teaching_class_id": other["tid"], "reason": "R6 confirmed metadata"}
            pre = call("POST", identity + "/preview", own["token"], json=link)
            call(
                "POST",
                identity + "/confirm",
                own["token"],
                json={**link, "revision": pre["revision"]},
            )
            for view in views:
                token, prefix = view["token"], view["prefix"]
                sample = {
                    "semester_id": sid,
                    "date_from": str(today),
                    "date_to": str(today),
                    "counts": {view["ac"]: 1},
                    "draw_id": "r6",
                    "require_photo": True,
                }
                sp = call("POST", view["gp"] + "/inspection/sample-preview", token, json=sample)
                generated = call(
                    "POST",
                    view["gp"] + "/inspection/generate",
                    token,
                    json={**sample, "selection_revision": sp["selection_revision"]},
                )
                assert generated["created"] == 1, generated
                task = call("GET", prefix + f"/inspection-tasks?semester_id={sid}", token)["items"][
                    0
                ]
                view["task_id"] = task["id"]
                plan = call(
                    "POST",
                    view["gp"] + "/inspection/assignment-plans/preview",
                    token,
                    json={
                        "semester_id": sid,
                        "task_ids": [task["id"]],
                        "assignments": {task["id"]: str(view["volunteer_user"])},
                    },
                )
                commit_body = {"revision": plan["revision"]}
                call(
                    "POST",
                    view["gp"] + f"/inspection/assignment-plans/{plan['id']}/commit",
                    token,
                    json=commit_body,
                )
                # Genuine multipart photo, official submission, attendance, objection and report.
                png = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
                )
                photo = call(
                    "POST",
                    "/files",
                    view["volunteer_token"],
                    data={"category": "SUBMISSION_PHOTO"},
                    files={"file": ("scene.png", png, "image/png")},
                )
                call(
                    "POST",
                    f"/inspection-tasks/{task['id']}/submissions",
                    view["volunteer_token"],
                    json={
                        "result": "ABNORMAL",
                        "abnormal_items": [
                            {"student_id": view["student"].id, "attendance_type": "LATE"}
                        ],
                        "file_ids": [int(photo["id"])],
                    },
                )
                attendance = call("GET", "/me/attendance", view["student_token"])["items"][0]
                assert attendance["task"]["responsible_college_id"] == prefix.rsplit("/", 1)[1]
                assert str(photo["id"]) in attendance["photo_file_ids"]
                call("GET", f"/files/{photo['id']}/access", view["student_token"])
                call(
                    "GET",
                    f"/files/{photo['id']}/access",
                    views[1 - views.index(view)]["student_token"],
                    expected=404,
                )
                objection = call(
                    "POST",
                    f"/attendance/{attendance['id']}/objections",
                    view["student_token"],
                    json={"desired_type": "NORMAL", "reason": "R6 attendance proof"},
                )
                call(
                    "POST",
                    prefix + f"/objections/{objection['id']}/review",
                    token,
                    json={"decision": "APPROVED", "final_type": "NORMAL", "current_version": 1},
                )
                stats = call(
                    "GET", prefix + f"/statistics/semesters/{sid}/campus-dimensions", token
                )
                assert stats["check_person_times"] == 1, stats
            call("GET", other["prefix"] + "/academic/students", own["token"], expected=404)
            grant = call(
                "POST",
                other["prefix"] + "/grants",
                root,
                json={"user_id": str(teacher.id), "actions": ["student.read"]},
            )
            call("GET", other["prefix"] + "/academic/students", own["token"])
            call(
                "POST",
                other["prefix"] + f"/grants/{grant['id']}/revoke",
                root,
                json={"lock_version": grant["lock_version"]},
            )
            call("GET", other["prefix"] + "/academic/students", own["token"], expected=404)
            summary = call("GET", f"/school/statistics/semesters/{sid}/campus-dimensions", root)
            assert summary["check_person_times"] == 2 and summary["distinct_student_count"] == 2
            hold = min(int(os.environ.get("R6_BROWSER_HOLD_SECONDS", "0")), 90)
            if hold:
                context = Path(__file__).resolve().parents[3] / "R6_BROWSER_CONTEXT.json"
                done = context.with_suffix(".done")
                done.unlink(missing_ok=True)
                context.write_text(
                    json.dumps(
                        {
                            "port": port,
                            "semester_id": sid,
                            "username": "r6teacherA",
                            "password": password,
                            "college_id": a["id"],
                        }
                    ),
                    encoding="utf-8",
                )
                context.chmod(0o600)
                try:
                    deadline = time.monotonic() + hold
                    while time.monotonic() < deadline and not done.exists():
                        time.sleep(0.2)
                finally:
                    context.unlink(missing_ok=True)
                    done.unlink(missing_ok=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
