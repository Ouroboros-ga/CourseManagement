"""查课 P4 Wave 3c：取消 / 名单改版 / 截止配置 / 截止时考核结算 集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P4 与技术方案 9.2 / 12 / 13：
- 认证与功能守卫：无令牌 401；缺 cancel/roster.manage/deadline.read/manage → 403。
- 取消（inspection.cancel）：happy 置取消、lock_version++、审计；重复取消 409；版本不符 409。
- 关键不变式：取消前按旧截止幂等结算，锁定既有逾期事实（截止已过者取消后仍 OVERDUE）。
- 结算（submission_deadline.manage，有界同步）：到期未取消 → OVERDUE_UNEXECUTED；截止前已取消 →
  CANCELED；未到期 → 不生成快照（deadlineAssessment null）；重复结算幂等（SKIP）；真实并发恰好一行。
- 截止配置：GET default（反射配置）；days 列表 / 单日 / 版本历史；PUT 改期乐观锁 +
  ≥当日最晚任务结束下界校验（DEADLINE_BEFORE_TASK_END）+ 改期前先结算锁定既有事实。
- 名单改版（inspection.roster.manage）：新版本 + 冻结快照 + expected_count_current；
  非存在/非在读学生 422；版本不符 409；已取消 409；roster.read 版本历史与可见性。
"""

from __future__ import annotations

import threading
from datetime import date as date_
from datetime import timedelta
from typing import Any

import pytest
from app.core.database import utcnow
from app.core.exceptions import ErrorCode
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password
from app.modules.academic.models import Student
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    DeadlineAssessmentResult,
    InspectionTask,
    SubmissionDeadlineDay,
    TaskDeadlineAssessment,
)
from app.modules.inspection.schemas import DeadlineSettleRequest
from app.modules.inspection.service import InspectionService
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"
_DL = "/api/v1/submission-deadlines"
_MON1 = "2026-09-07"  # 第 1 周周一（被查任务的查课日）
_MON1_D = date_(2026, 9, 7)


# --------------------------------------------------------------------------- #
# 装配助手
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    sync_registry(session)
    session.commit()


def _role(session: Session, code: str) -> Role:
    return session.execute(select(Role).where(Role.code == code)).scalar_one()


def _make_user(
    session: Session, username: str, role_codes: list[str], *, student_id: int | None = None
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


def _make_perm_user(session: Session, username: str, perm_codes: list[str]) -> UserAccount:
    role = Role(code=f"CUSTOM_{username}", name=f"custom-{username}")
    perms = [
        session.execute(select(Permission).where(Permission.code == c)).scalar_one()
        for c in perm_codes
    ]
    role.permissions = perms
    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    session.add_all([role, user])
    session.commit()
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/web/login", json={"username": username, "password": _PWD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


def _admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


def _post(client: TestClient, headers: dict[str, str], url: str, body: dict):
    resp = client.post(url, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


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
    body = {"course_code": code, "course_name": f"课程{code}"}
    return int(_post(client, h, f"{_ACA}/courses", body)["id"])


def _create_tc(
    client: TestClient, h: dict[str, str], sem_id: int, course_id: int, code: str
) -> int:
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


def _enroll(client: TestClient, h: dict[str, str], tc_id: int, student_ids: list[int]) -> None:
    rp = client.put(
        f"{_ACA}/teaching-classes/{tc_id}/students", headers=h, json={"student_ids": student_ids}
    )
    assert rp.status_code == 200, rp.text


def _schedule(
    client: TestClient, h: dict[str, str], tc_id: int, start: int, end: int, classroom: str
) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/course-schedules",
        {"teaching_class_id": tc_id, "weekday": 1, "start_period": start, "end_period": end,
         "classroom": classroom, "weeks": [1]},
    )
    return int(d["id"])


def _upsert_period(client: TestClient, h: dict[str, str], sem_id: int, no: int, end: str) -> None:
    rp = client.put(
        f"{_ACA}/semesters/{sem_id}/period-definitions/{no}",
        headers=h,
        json={"end_time": end, "reason": "节次时刻"},
    )
    assert rp.status_code == 200, rp.text


def _gen_course(client: TestClient, h: dict[str, str], sem_id: int, tc_ids: list[int]) -> int:
    d = _post(
        client,
        h,
        _GEN,
        {"semester_id": sem_id, "inspection_type": "COURSE", "week_nos": [1],
         "teaching_class_ids": tc_ids},
    )
    return int(d["created"])


def _list_tasks(client: TestClient, h: dict[str, str], sem_id: int) -> list[dict[str, Any]]:
    resp = client.get(_TASKS, headers=h, params={"semester_id": sem_id, "limit": 50})
    assert resp.status_code == 200, resp.text
    return list(resp.json()["data"]["items"])


def _grant_qual(client: TestClient, h: dict[str, str], sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={"semester_id": sem_id, "student_id": student_id, "enabled": True, "reason": "合格"},
    )
    assert rp.status_code == 200, rp.text


def _assign(
    client: TestClient, h: dict[str, str], task_id: int, vol_id: int, version: int = 0
) -> None:
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol_id, "lock_version": version},
    )
    assert resp.status_code == 200, resp.text


def _scene(client: TestClient, h: dict[str, str]) -> dict:
    """ACTIVE 学期 + 被查班 CS2401(两生) + 教学班 T1 + 周一 1-2 节，生成 1 任务、1 日截止 v1。"""
    sem = _post(
        client,
        h,
        f"{_ACA}/semesters",
        {"code": "2026FA", "name": "2026秋", "start_date": "2026-09-01", "end_date": "2027-01-31",
         "first_monday": _MON1, "total_weeks": 20},
    )
    sem_id = int(sem["id"])
    cs = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs)
    s2 = _create_student(client, h, "S002", cs)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    _enroll(client, h, t1, [s1, s2])
    _schedule(client, h, t1, 1, 2, "A101")
    assert _gen_course(client, h, sem_id, [t1]) == 1
    tasks = _list_tasks(client, h, sem_id)
    assert len(tasks) == 1
    return {"sem_id": sem_id, "cs": cs, "s1": s1, "s2": s2, "task": tasks[0],
            "task_id": int(tasks[0]["id"])}


# --------------------------------------------------------------------------- #
# 截止日/结算读助手（HTTP 提交后须结束夹具读事务再取新快照）
# --------------------------------------------------------------------------- #
def _get_day(session: Session, sem_id: int, on_date: date_) -> SubmissionDeadlineDay:
    session.commit()
    session.expire_all()
    return session.execute(
        select(SubmissionDeadlineDay).where(
            SubmissionDeadlineDay.semester_id == sem_id,
            SubmissionDeadlineDay.inspection_date == on_date,
        )
    ).scalar_one()


def _shift_deadline(
    session: Session, sem_id: int, on_date: date_, *, hours: int
) -> SubmissionDeadlineDay:
    day = _get_day(session, sem_id, on_date)
    day.deadline_at = utcnow() + timedelta(hours=hours)
    session.commit()
    return day


def _assessment(session: Session, task_id: int) -> TaskDeadlineAssessment | None:
    session.commit()
    session.expire_all()
    return session.execute(
        select(TaskDeadlineAssessment).where(TaskDeadlineAssessment.task_id == task_id)
    ).scalar_one_or_none()


def _count_assessments(session: Session, task_id: int) -> int:
    session.commit()
    session.expire_all()
    return int(
        session.execute(
            select(func.count())
            .select_from(TaskDeadlineAssessment)
            .where(TaskDeadlineAssessment.task_id == task_id)
        ).scalar_one()
    )


def _count(session: Session, model) -> int:
    session.commit()
    session.expire_all()
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def _audit_actions(session: Session, action: str) -> int:
    session.commit()
    session.expire_all()
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


def _settle(client: TestClient, h: dict[str, str], body: dict) -> dict:
    return _post(client, h, f"{_DL}/settle", body)


# --------------------------------------------------------------------------- #
# 认证与功能守卫
# --------------------------------------------------------------------------- #
def test_wave3c_requires_auth_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    r_cancel = client.post(f"{_TASKS}/1/cancel", json={"reason": "x", "lock_version": 0})
    assert r_cancel.status_code == 401
    assert client.post(
        f"{_TASKS}/1/roster-versions", json={"student_ids": [], "reason": "x", "lock_version": 0}
    ).status_code == 401
    assert client.get(f"{_TASKS}/1/roster-versions").status_code == 401
    assert client.get(f"{_DL}/default").status_code == 401
    assert client.get(_DL + "/days", params={"semester_id": 1}).status_code == 401
    assert client.put(
        f"{_DL}/days/{_MON1}", params={"semester_id": 1},
        json={"time": "23:00", "reason": "x", "lock_version": 1},
    ).status_code == 401
    assert client.post(f"{_DL}/settle", json={"semester_id": 1}).status_code == 401


def test_volunteer_guard_boundaries(client: TestClient, session: Session) -> None:
    # 志愿者有 roster.read 但无 roster.manage / cancel / deadline.read。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    sid = _create_student(client, h, "V001", other)
    _grant_qual(client, h, sc["sem_id"], sid)
    vol = _make_user(session, "vol", [RoleCode.VOLUNTEER.value], student_id=sid)
    _assign(client, h, sc["task_id"], vol.id)  # 令该任务进入志愿者可见范围
    vh = _bearer(_login(client, "vol"))
    # roster.read 具备 + 任务可见：版本历史可读。
    assert client.get(f"{_TASKS}/{sc['task_id']}/roster-versions", headers=vh).status_code == 200
    # 缺 deadline.read / cancel / roster.manage → 路由守卫即 403。
    assert client.get(f"{_DL}/default", headers=vh).status_code == 403
    assert client.post(
        f"{_TASKS}/{sc['task_id']}/cancel", headers=vh, json={"reason": "x", "lock_version": 1}
    ).status_code == 403
    assert client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=vh,
        json={"student_ids": [sc["s1"]], "reason": "x", "lock_version": 1},
    ).status_code == 403
    assert vol.id > 0


def test_deadline_reader_cannot_manage(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _make_perm_user(session, "dl_reader", [PermissionCode.SUBMISSION_DEADLINE_READ.value])
    rh = _bearer(_login(client, "dl_reader"))
    assert client.get(f"{_DL}/default", headers=rh).status_code == 200
    r_days = client.get(_DL + "/days", headers=rh, params={"semester_id": sc["sem_id"]})
    assert r_days.status_code == 200
    assert client.put(
        f"{_DL}/days/{_MON1}", headers=rh, params={"semester_id": sc["sem_id"]},
        json={"time": "23:00", "reason": "x", "lock_version": 1},
    ).status_code == 403
    r_settle = client.post(f"{_DL}/settle", headers=rh, json={"semester_id": sc["sem_id"]})
    assert r_settle.status_code == 403


# --------------------------------------------------------------------------- #
# 取消
# --------------------------------------------------------------------------- #
def test_cancel_happy_and_guards(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    tid = sc["task_id"]
    assert int(sc["task"]["lock_version"]) == 0
    resp = client.post(
        f"{_TASKS}/{tid}/cancel", headers=h,
        json={"reason": "该课临时停课", "lock_version": 0},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["status"] == "已取消"
    assert int(d["lock_version"]) == 1
    session.commit()
    session.expire_all()
    task = session.get(InspectionTask, tid)
    assert task is not None and task.canceled_at is not None
    assert task.cancel_reason == "该课临时停课"
    assert _audit_actions(session, "inspection.task.cancel") == 1
    # 重复取消 → 409 STATE_CONFLICT。
    again = client.post(
        f"{_TASKS}/{tid}/cancel", headers=h, json={"reason": "再取消", "lock_version": 1}
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == ErrorCode.STATE_CONFLICT.value
    # 不存在 → 404。
    assert client.post(f"{_TASKS}/999999/cancel", headers=h,
                       json={"reason": "x", "lock_version": 0}).status_code == 404


def test_cancel_version_conflict(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    resp = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                       json={"reason": "版本不符", "lock_version": 7})
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == ErrorCode.VERSION_CONFLICT.value


def test_cancel_locks_prior_overdue_fact(client: TestClient, session: Session) -> None:
    # 截止已过再取消：取消前按旧截止幂等结算 → 逾期事实被锁定为 OVERDUE_UNEXECUTED，
    # 不因后续取消而改写（技术方案 13.3 迟到/取消不改既有截止时事实）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-2)  # 截止在过去
    resp = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                       json={"reason": "截止后取消", "lock_version": 0})
    assert resp.status_code == 200, resp.text
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.OVERDUE_UNEXECUTED.value


# --------------------------------------------------------------------------- #
# 结算：到期 / 未到期 / 截止前取消 / 幂等 / 真实并发
# --------------------------------------------------------------------------- #
def test_settle_overdue_and_idempotent(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-2)
    r1 = _settle(client, h, {"semester_id": sc["sem_id"], "inspection_date": _MON1})
    assert r1["settled"] >= 1
    assert any(int(x["task_id"]) == sc["task_id"] and x["result"] == "OVERDUE_UNEXECUTED"
               for x in r1["results"])
    assert _count_assessments(session, sc["task_id"]) == 1
    # 再结算：已结算任务被 unsettled 查询过滤，不重复建行（幂等）。
    r2 = _settle(client, h, {"semester_id": sc["sem_id"], "inspection_date": _MON1})
    assert r2["settled"] == 0
    assert r2["considered"] == 0
    assert _count_assessments(session, sc["task_id"]) == 1
    assert _audit_actions(session, "submission_deadline.settle") == 2


def test_settle_not_due_creates_no_snapshot(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 未来截止
    r = _settle(client, h, {"semester_id": sc["sem_id"], "inspection_date": _MON1})
    assert r["not_due"] >= 1
    assert r["settled"] == 0
    assert _assessment(session, sc["task_id"]) is None
    # 任务视图中 deadlineAssessment 为 null。
    detail = client.get(f"{_TASKS}/{sc['task_id']}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["deadline_assessment"] is None


def test_settle_canceled_before_deadline(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 未来截止
    # 直接置取消（取消时刻早于未来截止）：结算应判 CANCELED（不纳入未完成）。
    day = _get_day(session, sc["sem_id"], _MON1_D)
    session.commit()
    session.expire_all()
    task = session.get(InspectionTask, sc["task_id"])
    assert task is not None
    task.canceled_at = utcnow()  # <= 未来 deadline
    session.commit()
    r = _settle(client, h, {"semester_id": sc["sem_id"], "task_ids": [sc["task_id"]]})
    assert r["settled"] >= 1
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.CANCELED.value
    assert day.version == 1  # 结算不改截止版本


def _settle_worker(
    engine: Engine, actor_id: int, sem_id: int, task_id: int,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="admin", display_name="admin",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        body = DeadlineSettleRequest(semester_id=sem_id, task_ids=[task_id], limit=10)
        barrier.wait()
        InspectionService(s).settle_deadline(actor, body, f"conc-{idx}")
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_settle_single_row(
    client: TestClient, engine: Engine, session: Session
) -> None:
    # 多连接同时结算同一到期任务：任务行 FOR UPDATE 串行化 + 已有快照复查用锁定读
    # （绕过 REPEATABLE READ 旧快照）→ 恰好一行 assessment，且落败方走 SKIP 返回 ok 而非 500。
    # 4 线程提高真实交叠概率：若快照复查退回非锁定读，本用例会因撞唯一约束而间歇性变红。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-2)
    admin = session.execute(select(UserAccount).where(UserAccount.username == "admin")).scalar_one()
    session.commit()
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(4)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(target=_settle_worker,
                         args=(engine, admin.id, sc["sem_id"], sc["task_id"], barrier, out, i))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(out) == 4, out
    assert all(r[0] == "ok" for r in out.values()), out
    assert _count_assessments(session, sc["task_id"]) == 1


# --------------------------------------------------------------------------- #
# 截止配置：默认值 / 列表 / 单日 / 版本历史 / 改期乐观锁
# --------------------------------------------------------------------------- #
def test_deadline_default_readonly(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    _scene(client, h)
    d = client.get(f"{_DL}/default", headers=h).json()["data"]
    assert d["time"] == "22:00"
    assert d["utc_offset_hours"] == 8.0
    assert d["description"]


def test_deadline_day_list_detail_versions(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    days = client.get(_DL + "/days", headers=h, params={"semester_id": sc["sem_id"]}).json()["data"]
    assert len(days) == 1
    assert days[0]["version"] == 1
    assert int(days[0]["task_count"]) == 1
    one = client.get(f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]})
    assert one.status_code == 200, one.text
    assert one.json()["data"]["version"] == 1
    vers = client.get(f"{_DL}/days/{_MON1}/versions", headers=h,
                      params={"semester_id": sc["sem_id"]}).json()["data"]
    assert len(vers) == 1
    assert vers[0]["version_no"] == 1
    # 无截止记录的日期 → 404。
    assert client.get(f"{_DL}/days/2030-01-01", headers=h,
                      params={"semester_id": sc["sem_id"]}).status_code == 404


def test_deadline_day_update_flow(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 改期：v1 → v2，写版本历史。
    ok = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "23:30", "reason": "延长提交窗口", "lock_version": 1},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["version"] == 2
    vers = client.get(f"{_DL}/days/{_MON1}/versions", headers=h,
                      params={"semester_id": sc["sem_id"]}).json()["data"]
    assert [v["version_no"] for v in vers] == [1, 2]
    assert _audit_actions(session, "submission_deadline.day_update") == 1
    # 用旧版本再改 → 乐观锁 409。
    stale = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "23:45", "reason": "旧版本", "lock_version": 1},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == ErrorCode.VERSION_CONFLICT.value


def test_deadline_update_preserves_overdue(client: TestClient, session: Session) -> None:
    # 改期前对该日未结算任务按旧截止结算锁定既有逾期；改晚也不清除已结算事实（技术方案 13.3）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-2)
    resp = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "23:59", "reason": "改晚", "lock_version": 1},
    )
    assert resp.status_code == 200, resp.text
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.OVERDUE_UNEXECUTED.value


def test_deadline_update_before_task_end_422(client: TestClient, session: Session) -> None:
    # 配置节次 2 结束于 10:30；改期到 09:00（早于当日最晚任务结束）→ 422 拒绝。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _upsert_period(client, h, sc["sem_id"], 2, "10:30")
    early = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "09:00", "reason": "过早", "lock_version": 1},
    )
    assert early.status_code == 422, early.text
    assert early.json()["fieldErrors"]["reason_code"] == "DEADLINE_BEFORE_TASK_END"
    # 改到 11:00（晚于任务结束）→ 通过。
    late = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "11:00", "reason": "合理", "lock_version": 1},
    )
    assert late.status_code == 200, late.text
    assert late.json()["data"]["version"] == 2


def test_deadline_bad_time_format_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    resp = client.put(
        f"{_DL}/days/{_MON1}", headers=h, params={"semester_id": sc["sem_id"]},
        json={"time": "25:99", "reason": "非法", "lock_version": 1},
    )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# 名单改版
# --------------------------------------------------------------------------- #
def test_roster_version_revise(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    s3 = _create_student(client, h, "S003", sc["cs"])
    resp = client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h,
        json={"student_ids": [sc["s1"], sc["s2"], s3], "reason": "补录转班生", "lock_version": 0},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert int(d["roster_version"]) == 2
    assert int(d["expected_count_current"]) == 3
    assert int(d["lock_version"]) == 1
    assert _audit_actions(session, "inspection.roster.revise") == 1
    # 版本历史：v1(2 人) + v2(3 人)。
    hist = client.get(f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h).json()["data"]
    assert [v["version_no"] for v in hist] == [1, 2]
    assert [v["member_count"] for v in hist] == [2, 3]


def test_roster_version_missing_and_inactive(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    missing = client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h,
        json={"student_ids": [999_999], "reason": "不存在", "lock_version": 0},
    )
    assert missing.status_code == 422, missing.text
    assert missing.json()["fieldErrors"]["missing_student_ids"] == [999_999]
    # 非在读（ARCHIVED）学生：直接入库一个归档生再提交。
    archived = Student(student_no="Z001", name="归档生",
                       administrative_class_id=sc["cs"], status="ARCHIVED")
    session.add(archived)
    session.commit()
    session.expire_all()
    inactive = client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h,
        json={"student_ids": [archived.id], "reason": "含归档", "lock_version": 0},
    )
    assert inactive.status_code == 422, inactive.text
    assert archived.id in inactive.json()["fieldErrors"]["inactive_student_ids"]


def test_roster_version_state_and_lock(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 版本不符 → 409。
    wrong = client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h,
        json={"student_ids": [sc["s1"]], "reason": "版本不符", "lock_version": 5},
    )
    assert wrong.status_code == 409, wrong.text
    assert wrong.json()["code"] == ErrorCode.VERSION_CONFLICT.value
    # 先取消，再改版 → 409 STATE_CONFLICT。
    c = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                    json={"reason": "停课", "lock_version": 0})
    assert c.status_code == 200, c.text
    canceled = client.post(
        f"{_TASKS}/{sc['task_id']}/roster-versions", headers=h,
        json={"student_ids": [sc["s1"]], "reason": "已取消", "lock_version": 1},
    )
    assert canceled.status_code == 409, canceled.text
    assert canceled.json()["code"] == ErrorCode.STATE_CONFLICT.value


# --------------------------------------------------------------------------- #
# 五态精判：截止已过且未取消 → 已逾期
# --------------------------------------------------------------------------- #
def test_five_state_overdue_and_pending(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 把截止推到未来 → 未到期：待执行。
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)
    detail = client.get(f"{_TASKS}/{sc['task_id']}", headers=h).json()["data"]
    assert detail["status"] == "待执行"
    # 再把截止改到过去 → 已逾期。
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-1)
    after = client.get(f"{_TASKS}/{sc['task_id']}", headers=h).json()["data"]
    assert after["status"] == "已逾期"
