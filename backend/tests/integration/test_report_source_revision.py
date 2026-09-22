"""报表源修订基础设施 P7(W7b)：影响考勤的写路径同事务原子递增，连真实 MySQL。

覆盖技术方案 9.4 与 P6 挂账的集中偿还：
- 审核通过生成考勤 → (学期,周) revision +1；审核驳回不改考勤 → 不递增。
- 应到人数调整：真实变化才 +1；调整为同值（无变化）不递增。
- 考勤更正 → 所属任务 (学期,周) +1。
- 异议终审：改判实际更正考勤才 +1；终审通过但维持原认定不递增。
- 累计与维度隔离：同 (学期,周) 多次变更单调累加；未命中周次不建行。
- 并发：多线程对同一 (学期,周) 并发 bump（独立连接、同主键 UPSERT 自增），
  revision 单调无丢失（最终值 = 初始 + 成功次数）。
"""

from __future__ import annotations

import threading
from datetime import date as date_
from datetime import timedelta
from typing import Any

import pytest
from app.core.database import utcnow
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.modules.identity.models import Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.inspection.models import InspectionTask, SubmissionDeadlineDay
from app.modules.report.models import ReportSourceRevision
from app.modules.report.source_revision import SourceRevisionService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"
_SUBS = "/api/v1/submissions"
_ATT = "/api/v1/attendance"
_OBJS = "/api/v1/objections"
_MON1 = "2026-09-07"
_MON1_D = date_(2026, 9, 7)


# --------------------------------------------------------------------------- #
# 装配助手（与 test_objection 同构，令本文件自包含）
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    sync_registry(session)
    session.commit()


def _role(session: Session, code: str) -> Role:
    return session.execute(select(Role).where(Role.code == code)).scalar_one()


def _make_user(
    session: Session,
    username: str,
    role_codes: list[str],
    *,
    student_id: int | None = None,
) -> UserAccount:
    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
        student_id=student_id,
    )
    user.roles = [_role(session, c) for c in role_codes]
    session.add(user)
    session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/web/login", json={"username": username, "password": _PWD})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


def _post(client: TestClient, h: dict[str, str], url: str, body: dict) -> dict:
    resp = client.post(url, headers=h, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _patch(client: TestClient, h: dict[str, str], url: str, body: dict) -> dict:
    resp = client.patch(url, headers=h, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


def _create_admin_class(client: TestClient, h: dict[str, str], code: str) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/administrative-classes",
        {
            "class_code": code,
            "class_name": f"班{code}",
            "college": "计算机学院",
            "grade_year": 2024,
        },
    )
    return int(d["id"])


def _create_student(client: TestClient, h: dict[str, str], no: str, class_id: int) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/students",
        {"student_no": no, "name": f"学生{no}", "administrative_class_id": class_id},
    )
    return int(d["id"])


def _create_course(client: TestClient, h: dict[str, str], code: str) -> int:
    d = _post(client, h, f"{_ACA}/courses", {"course_code": code, "course_name": f"课程{code}"})
    return int(d["id"])


def _create_tc(client, h, sem_id: int, course_id: int, code: str) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/teaching-classes",
        {
            "semester_id": sem_id,
            "course_id": course_id,
            "class_code": code,
            "class_name": f"班{code}",
        },
    )
    return int(d["id"])


def _enroll(client: TestClient, h: dict[str, str], tc_id: int, sids: list[int]) -> None:
    rp = client.put(
        f"{_ACA}/teaching-classes/{tc_id}/students", headers=h, json={"student_ids": sids}
    )
    assert rp.status_code == 200, rp.text


def _schedule(client, h, tc_id: int, start: int, end: int, room: str, week: int = 1) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/course-schedules",
        {
            "teaching_class_id": tc_id,
            "weekday": 1,
            "start_period": start,
            "end_period": end,
            "classroom": room,
            "weeks": [week],
        },
    )
    return int(d["id"])


def _gen_course(client, h, sem_id: int, tc_ids: list[int], weeks: list[int]) -> int:
    d = _post(
        client,
        h,
        _GEN,
        {
            "semester_id": sem_id,
            "inspection_type": "COURSE",
            "week_nos": weeks,
            "teaching_class_ids": tc_ids,
        },
    )
    return int(d["created"])


def _list_tasks(client: TestClient, h: dict[str, str], sem_id: int) -> list[dict[str, Any]]:
    resp = client.get(_TASKS, headers=h, params={"semester_id": sem_id, "limit": 50})
    assert resp.status_code == 200, resp.text
    return list(resp.json()["data"]["items"])


def _grant_qual(client, h, sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={"semester_id": sem_id, "student_id": student_id, "enabled": True, "reason": "合格"},
    )
    assert rp.status_code == 200, rp.text


def _task_lock_version(session: Session, task_id: int) -> int:
    session.commit()
    session.expire_all()
    row = session.get(InspectionTask, task_id)
    assert row is not None
    return int(row.lock_version)


def _make_volunteer_for_task(
    client, h, session: Session, sem_id: int, task_id: int, username: str
) -> dict[str, str]:
    other = _create_admin_class(client, h, f"VCLASS_{username}")
    sid = _create_student(client, h, f"V{username}", other)
    _grant_qual(client, h, sem_id, sid)
    vol = _make_user(session, username, [RoleCode.VOLUNTEER.value], student_id=sid)
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": _task_lock_version(session, task_id)},
    )
    assert resp.status_code == 200, resp.text
    return _bearer(_login(client, username))


def _shift_deadline(session: Session, sem_id: int, on_date: date_, *, hours: int) -> None:
    session.commit()
    session.expire_all()
    day = session.execute(
        select(SubmissionDeadlineDay).where(
            SubmissionDeadlineDay.semester_id == sem_id,
            SubmissionDeadlineDay.inspection_date == on_date,
        )
    ).scalar_one()
    day.deadline_at = utcnow() + timedelta(hours=hours)
    session.commit()


def _submit_abnormal(client, h, session, sem_id, task_id, s1, *, s2_type=None) -> int:
    """志愿者提交 ABNORMAL（s1=LATE[+可选 s2]）→ sub_id。截止回拨到未来保证按时。"""
    _shift_deadline(session, sem_id, _MON1_D, hours=+48)
    vh = _make_volunteer_for_task(client, h, session, sem_id, task_id, f"vol{task_id}")
    items: list[dict] = [{"student_id": s1, "attendance_type": "LATE", "note": "迟到"}]
    body = {"result": "ABNORMAL", "abnormal_items": items, "file_ids": []}
    r = client.post(f"{_TASKS}/{task_id}/submissions", headers=vh, json=body)
    assert r.status_code == 200, r.text
    _ = s2_type
    return int(r.json()["data"]["id"])


def _approve(client, h, sub_id: int) -> None:
    r = client.post(f"{_SUBS}/{sub_id}/review", headers=h, json={"decision": "APPROVED"})
    assert r.status_code == 200, r.text


def _scene(client: TestClient, h: dict[str, str], session: Session) -> dict:
    """ACTIVE 学期 + CS2401(S001/S002) + 教学班 T1(week1) → 1 任务；无 report 源修订行。"""
    sem = _post(
        client,
        h,
        f"{_ACA}/semesters",
        {
            "code": "2026FA",
            "name": "2026秋",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": _MON1,
            "total_weeks": 20,
        },
    )
    sem_id = int(sem["id"])
    cs = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs)
    s2 = _create_student(client, h, "S002", cs)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    _enroll(client, h, t1, [s1, s2])
    _schedule(client, h, t1, 1, 2, "A101", 1)
    assert _gen_course(client, h, sem_id, [t1], [1]) == 1
    tasks = _list_tasks(client, h, sem_id)
    assert len(tasks) == 1
    return {"sem_id": sem_id, "s1": s1, "s2": s2, "task_id": int(tasks[0]["id"]), "week": 1}


def _record_ids(session: Session, task_id: int) -> dict[int, int]:
    """审核生成考勤后，{student_id: attendance_record_id}。"""
    from app.modules.attendance.models import AttendanceRecord

    session.commit()
    session.expire_all()
    rows = session.execute(
        select(AttendanceRecord).where(AttendanceRecord.task_id == task_id)
    ).scalars()
    return {r.student_id: r.id for r in rows}


# --------------------------------------------------------------------------- #
# 事实读助手：源修订号
# --------------------------------------------------------------------------- #
def _revision(session: Session, sem_id: int, week_no: int) -> int | None:
    session.commit()
    session.expire_all()
    val = session.execute(
        select(ReportSourceRevision.revision).where(
            ReportSourceRevision.semester_id == sem_id,
            ReportSourceRevision.week_no == week_no,
        )
    ).scalar_one_or_none()
    return None if val is None else int(val)


# --------------------------------------------------------------------------- #
# 路径一：审核通过生成考勤
# --------------------------------------------------------------------------- #
def test_review_approval_bumps(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    assert _revision(session, sc["sem_id"], 1) is None  # 生成任务不触发源修订
    sub_id = _submit_abnormal(client, h, session, sc["sem_id"], sc["task_id"], sc["s1"])
    _approve(client, h, sub_id)
    assert _revision(session, sc["sem_id"], 1) == 1


def test_review_rejection_does_not_bump(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    sub_id = _submit_abnormal(client, h, session, sc["sem_id"], sc["task_id"], sc["s1"])
    r = client.post(f"{_SUBS}/{sub_id}/review", headers=h, json={"decision": "REJECTED"})
    assert r.status_code == 200, r.text
    # 驳回不改考勤事实 → 无源修订行。
    assert _revision(session, sc["sem_id"], 1) is None


# --------------------------------------------------------------------------- #
# 路径二：应到人数调整（真实变化才递增）
# --------------------------------------------------------------------------- #
def test_expected_count_change_bumps(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _patch(
        client,
        h,
        f"{_TASKS}/{sc['task_id']}/expected-count",
        {
            "expected_count_current": 10,
            "reason": "复核应到",
            "lock_version": _task_lock_version(session, sc["task_id"]),
        },
    )
    assert _revision(session, sc["sem_id"], 1) == 1


def test_expected_count_noop_does_not_bump(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    # 先读到初始当前应到值，再"调整"成同一值 → 不算源变更。
    session.commit()
    session.expire_all()
    task = session.get(InspectionTask, sc["task_id"])
    assert task is not None
    cur = int(task.expected_count_current)
    _patch(
        client,
        h,
        f"{_TASKS}/{sc['task_id']}/expected-count",
        {
            "expected_count_current": cur,
            "reason": "维持不变",
            "lock_version": _task_lock_version(session, sc["task_id"]),
        },
    )
    assert _revision(session, sc["sem_id"], 1) is None


# --------------------------------------------------------------------------- #
# 路径三：考勤更正
# --------------------------------------------------------------------------- #
def test_attendance_correction_bumps(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    sub_id = _submit_abnormal(client, h, session, sc["sem_id"], sc["task_id"], sc["s1"])
    _approve(client, h, sub_id)
    assert _revision(session, sc["sem_id"], 1) == 1  # 审核已 +1
    rec_ids = _record_ids(session, sc["task_id"])
    rid = rec_ids[sc["s2"]]  # s2=NORMAL 初始
    _post(
        client,
        h,
        f"{_ATT}/{rid}/corrections",
        {"attendance_type": "ABSENT", "reason": "补录旷课", "current_version": 1},
    )
    assert _revision(session, sc["sem_id"], 1) == 2  # 更正再 +1


# --------------------------------------------------------------------------- #
# 路径四：异议终审（改判才递增）
# --------------------------------------------------------------------------- #
def _open_objection_on_s2(client, h, session, sc, *, desired="LATE") -> tuple[int, int]:
    sub_id = _submit_abnormal(client, h, session, sc["sem_id"], sc["task_id"], sc["s1"])
    _approve(client, h, sub_id)
    rec_ids = _record_ids(session, sc["task_id"])
    rid = rec_ids[sc["s2"]]  # s2=NORMAL
    stu = _make_user(session, "stu_s2", [RoleCode.STUDENT.value], student_id=sc["s2"])
    sh = _bearer(_login(client, "stu_s2"))
    _ = stu
    obj = _post(
        client, sh, f"{_ATT}/{rid}/objections", {"desired_type": desired, "reason": "其实迟到"}
    )
    return int(obj["id"]), rid


def test_objection_final_correction_bumps(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    oid, _rid = _open_objection_on_s2(client, h, session, sc, desired="LATE")
    base = _revision(session, sc["sem_id"], 1)  # 审核通过带来的基数（=1）
    assert base == 1
    r = client.post(
        f"{_OBJS}/{oid}/final-review",
        headers=h,
        json={"decision": "APPROVED", "final_type": "LATE", "current_version": 1},
    )
    assert r.status_code == 200, r.text
    assert _revision(session, sc["sem_id"], 1) == 2  # 改判更正 → 再 +1


def test_objection_final_no_correction_does_not_bump(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    oid, _rid = _open_objection_on_s2(client, h, session, sc, desired="LATE")
    assert _revision(session, sc["sem_id"], 1) == 1  # 仅审核一次
    # 终审通过但维持 NORMAL（与当前一致）→ 关闭异议、不改考勤 → 不再递增。
    r = client.post(
        f"{_OBJS}/{oid}/final-review",
        headers=h,
        json={"decision": "APPROVED", "final_type": "NORMAL", "current_version": 1},
    )
    assert r.status_code == 200, r.text
    assert _revision(session, sc["sem_id"], 1) == 1


# --------------------------------------------------------------------------- #
# 累计 + 维度隔离
# --------------------------------------------------------------------------- #
def test_cumulative_and_week_isolation(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    # week1 场景 + week2 独立教学班，验证两维度各自计。
    sem = _post(
        client,
        h,
        f"{_ACA}/semesters",
        {
            "code": "2026FA",
            "name": "2026秋",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": _MON1,
            "total_weeks": 20,
        },
    )
    sem_id = int(sem["id"])
    cs = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs)
    s2 = _create_student(client, h, "S002", cs)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    _enroll(client, h, t1, [s1, s2])
    _schedule(client, h, t1, 1, 2, "A101", 1)
    assert _gen_course(client, h, sem_id, [t1], [1]) == 1
    t2 = _create_tc(client, h, sem_id, course, "T2")
    _enroll(client, h, t2, [s1, s2])
    _schedule(client, h, t2, 3, 4, "B201", 2)
    assert _gen_course(client, h, sem_id, [t2], [2]) == 1
    tasks = {int(t["week_no"]): int(t["id"]) for t in _list_tasks(client, h, sem_id)}

    # week1 连续两次源变更（审核 + 更正）。
    w1 = tasks[1]
    sub_id = _submit_abnormal(client, h, session, sem_id, w1, s1)
    _approve(client, h, sub_id)
    rec = _record_ids(session, w1)
    _post(
        client,
        h,
        f"{_ATT}/{rec[s2]}/corrections",
        {"attendance_type": "ABSENT", "reason": "更正", "current_version": 1},
    )
    # week2 仅一次审核。
    w2 = tasks[2]
    sub2 = _submit_abnormal(client, h, session, sem_id, w2, s1)
    _approve(client, h, sub2)

    assert _revision(session, sem_id, 1) == 2  # week1 累加
    assert _revision(session, sem_id, 2) == 1  # week2 独立
    assert _revision(session, sem_id, 3) is None  # 未命中周次不建行


# --------------------------------------------------------------------------- #
# 并发：同 (学期,周) 多线程 bump，单调无丢失
# --------------------------------------------------------------------------- #
def _bump_worker(
    engine: Engine, sem_id: int, week: int, barrier: threading.Barrier, out: dict, idx: int
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        barrier.wait()
        SourceRevisionService.bump(s, sem_id, week)
        s.commit()
        out[idx] = "ok"
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = f"error:{exc!r}"
    finally:
        s.close()


def test_concurrent_bumps_monotonic_no_loss(
    client: TestClient, engine: Engine, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    sem_id, week = sc["sem_id"], 1
    # 先建一行（模拟首次变更已发生），再从基数并发递增。
    _submit_abnormal(client, h, session, sem_id, sc["task_id"], sc["s1"])
    _approve(client, h, _latest_sub_id(session, sc["task_id"]))
    assert _revision(session, sem_id, week) == 1

    n = 6
    barrier: threading.Barrier = threading.Barrier(n)
    out: dict[int, str] = {}
    threads = [
        threading.Thread(target=_bump_worker, args=(engine, sem_id, week, barrier, out, i))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert list(out.values()) == ["ok"] * n, out
    # 基数 1 + 并发 6 次原子自增 = 7，无读-改-写丢失。
    assert _revision(session, sem_id, week) == 1 + n


def _latest_sub_id(session: Session, task_id: int) -> int:
    from app.modules.inspection.models import InspectionSubmission

    session.commit()
    session.expire_all()
    row = session.execute(
        select(InspectionSubmission.id)
        .where(InspectionSubmission.task_id == task_id)
        .order_by(InspectionSubmission.id.desc())
        .limit(1)
    ).scalar_one()
    return int(row)
