"""查课调班申请（P4 Wave 3b：志愿者发起、管理人员处理）集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P4 与技术方案 12.6 / PERMISSIONS.md 4.3：
- 功能守卫：无令牌 401；缺 change_request 创建/读 → 403；缺 change_review 处理 → 403。
- "当前受派人"边界：非本人受派创建 → 403；受派不存在 → 404。
- 发起 happy：PENDING 落库、task_id 回填、审计 assignment.change_request.create。
- 状态守卫：任务已取消 409；同受派已有 PENDING 再发起 409。
- 处理：PENDING→APPROVED/REJECTED、processed_by/at/comment、审计；重复处理 409；
  approve/reject 仅迁移申请状态，不改受派人（无隐式改派）。
- 读取范围：志愿者仅本人（/me）；管理视图读全部；状态过滤。
- 真实 MySQL 并发：两连接同时处理同一 PENDING 申请 → 恰好一次成功转态、另一次 409。
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    AssignmentChangeRequest,
    ChangeRequestStatus,
    InspectionAssignment,
    InspectionTask,
)
from app.modules.inspection.schemas import ChangeRequestReviewRequest
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
_CR = "/api/v1/assignment-change-requests"
_ME_CR = "/api/v1/me/assignment-change-requests"
_MON1 = "2026-09-07"  # 第 1 周周一


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
        f"{_ACA}/teaching-classes/{tc_id}/students",
        headers=h,
        json={"student_ids": student_ids},
    )
    assert rp.status_code == 200, rp.text


def _schedule(
    client: TestClient,
    h: dict[str, str],
    tc_id: int,
    start: int,
    end: int,
    classroom: str,
    weeks: list[int] | None = None,
    weekday: int = 1,
) -> int:
    d = _post(
        client,
        h,
        f"{_ACA}/course-schedules",
        {
            "teaching_class_id": tc_id,
            "weekday": weekday,
            "start_period": start,
            "end_period": end,
            "classroom": classroom,
            "weeks": weeks or [1],
        },
    )
    return int(d["id"])


def _grant_qual(client: TestClient, h: dict[str, str], sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={
            "semester_id": sem_id,
            "student_id": student_id,
            "enabled": True,
            "reason": "合格志愿者",
        },
    )
    assert rp.status_code == 200, rp.text


def _gen_course(client: TestClient, h: dict[str, str], sem_id: int, tc_ids: list[int]) -> int:
    d = _post(
        client,
        h,
        _GEN,
        {
            "semester_id": sem_id,
            "inspection_type": "COURSE",
            "week_nos": [1],
            "teaching_class_ids": tc_ids,
        },
    )
    return int(d["created"])


def _list_tasks(client: TestClient, h: dict[str, str], sem_id: int) -> list[dict[str, Any]]:
    resp = client.get(_TASKS, headers=h, params={"semester_id": sem_id, "limit": 50})
    assert resp.status_code == 200, resp.text
    return list(resp.json()["data"]["items"])


def _make_volunteer(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    *,
    sem_id: int,
    username: str,
    student_no: str,
    admin_class_id: int,
    qualify: bool = True,
    volunteer: bool = True,
) -> UserAccount:
    sid = _create_student(client, h, student_no, admin_class_id)
    roles = [RoleCode.VOLUNTEER.value] if volunteer else [RoleCode.STUDENT.value]
    acct = _make_user(session, username, roles, student_id=sid)
    if qualify:
        _grant_qual(client, h, sem_id, sid)
    return acct


def _one_task_scene(client: TestClient, h: dict[str, str]) -> dict:
    """ACTIVE 学期 + 被查行政班 CS2401 + 教学班 T1 + 周一 1-2 节课表，生成 1 个任务。"""
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
    cs2401 = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs2401)
    s2 = _create_student(client, h, "S002", cs2401)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    _enroll(client, h, t1, [s1, s2])
    _schedule(client, h, t1, 1, 2, "A101")
    assert _gen_course(client, h, sem_id, [t1]) == 1
    tasks = _list_tasks(client, h, sem_id)
    assert len(tasks) == 1
    return {"sem_id": sem_id, "cs2401": cs2401, "course": course, "task": tasks[0]}


def _add_second_task(client: TestClient, h: dict[str, str], sem_id: int) -> dict:
    """再造一个同日不重叠（8-9 节）的任务，供两名志愿者各受一派。"""
    course = _create_course(client, h, "C700")
    t2 = _create_tc(client, h, sem_id, course, "T2")
    other_roster = _create_admin_class(client, h, "CS3301")
    _enroll(client, h, t2, [_create_student(client, h, "S201", other_roster)])
    _schedule(client, h, t2, 8, 9, "A103")
    assert _gen_course(client, h, sem_id, [t2]) == 1
    tasks = _list_tasks(client, h, sem_id)
    return next(t for t in tasks if int(t["start_period"]) == 8)


def _assign(
    client: TestClient, h: dict[str, str], task_id: int, vol_id: int, version: int = 0
) -> None:
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol_id, "lock_version": version},
    )
    assert resp.status_code == 200, resp.text


def _assignment_id(session: Session, task_id: int) -> int:
    """取刚经 HTTP 提交的受派关系 id：结束夹具读事务再取新快照。"""
    session.commit()
    session.expire_all()
    a = session.execute(
        select(InspectionAssignment).where(InspectionAssignment.task_id == task_id)
    ).scalar_one()
    return int(a.id)


def _count(session: Session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def _audit_actions(session: Session, action: str) -> int:
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


def _assigned_volunteer_scene(
    client: TestClient, session: Session
) -> dict:
    """建 ACTIVE 场景 + 一名合格志愿者被人工受派；返回含 vol、task、assignment、请求头。"""
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="vol", student_no="V001",
        admin_class_id=other,
    )
    task_id = int(sc["task"]["id"])
    _assign(client, h, task_id, vol.id)
    assignment_id = _assignment_id(session, task_id)
    vol_h = _bearer(_login(client, "vol"))
    return {
        "h": h,
        "sc": sc,
        "vol": vol,
        "vol_h": vol_h,
        "task_id": task_id,
        "assignment_id": assignment_id,
    }


# --------------------------------------------------------------------------- #
# 认证与功能守卫
# --------------------------------------------------------------------------- #
def test_change_request_requires_auth_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    assert client.post(_CR, json={"assignment_id": 1, "reason": "x"}).status_code == 401
    assert client.get(_ME_CR).status_code == 401
    assert client.get(_CR).status_code == 401
    assert client.post(f"{_CR}/1/review", json={"decision": "APPROVED"}).status_code == 401


def test_volunteer_cannot_review_403(client: TestClient, session: Session) -> None:
    # 志愿者有 change_request 但无 change_review：处理他人申请在路由守卫即 403。
    sc = _assigned_volunteer_scene(client, session)
    other = _create_admin_class(client, sc["h"], "CS2403")
    vol2 = _make_volunteer(
        client, sc["h"], session, sem_id=sc["sc"]["sem_id"], username="vol2",
        student_no="V002", admin_class_id=other,
    )
    v2h = _bearer(_login(client, "vol2"))
    resp = client.post(
        f"{_CR}/1/review", headers=v2h, json={"decision": "APPROVED"}
    )
    assert resp.status_code == 403, resp.text
    assert vol2.id > 0


def test_reviewer_cannot_create_403(client: TestClient, session: Session) -> None:
    # 仅 change_review 的管理账号缺少 change_request：发起申请 403。
    _bootstrap(session)
    _make_perm_user(session, "reviewer", [PermissionCode.ASSIGNMENT_CHANGE_REVIEW.value])
    rh = _bearer(_login(client, "reviewer"))
    resp = client.post(_CR, headers=rh, json={"assignment_id": 1, "reason": "想调班"})
    assert resp.status_code == 403, resp.text


# --------------------------------------------------------------------------- #
# 发起：当前受派人边界 + happy + 状态守卫
# --------------------------------------------------------------------------- #
def test_create_requires_current_assignee(client: TestClient, session: Session) -> None:
    sc = _assigned_volunteer_scene(client, session)
    # 另一名志愿者（非该受派的当前受派人）试图代提 → 403。
    other = _create_admin_class(client, sc["h"], "CS2403")
    vol2 = _make_volunteer(
        client, sc["h"], session, sem_id=sc["sc"]["sem_id"], username="other",
        student_no="V009", admin_class_id=other,
    )
    v2h = _bearer(_login(client, "other"))
    denied = client.post(
        _CR, headers=v2h, json={"assignment_id": sc["assignment_id"], "reason": "代提"}
    )
    assert denied.status_code == 403, denied.text
    assert vol2.id > 0
    # 受派不存在 → 404。
    missing = client.post(
        _CR, headers=sc["vol_h"], json={"assignment_id": 999_999, "reason": "不存在"}
    )
    assert missing.status_code == 404, missing.text


def test_create_change_request_happy(client: TestClient, session: Session) -> None:
    sc = _assigned_volunteer_scene(client, session)
    resp = client.post(
        _CR,
        headers=sc["vol_h"],
        json={"assignment_id": sc["assignment_id"], "reason": "当天有急事需调班"},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["status"] == ChangeRequestStatus.PENDING.value
    assert int(d["assignment_id"]) == sc["assignment_id"]
    assert int(d["task_id"]) == sc["task_id"]
    assert int(d["request_user_id"]) == sc["vol"].id
    assert d["processed_by"] is None
    assert d["processed_at"] is None

    session.commit()
    session.expire_all()
    assert _count(session, AssignmentChangeRequest) == 1
    assert _audit_actions(session, "assignment.change_request.create") == 1


def test_create_canceled_task_409(client: TestClient, session: Session) -> None:
    from app.core.database import utcnow

    sc = _assigned_volunteer_scene(client, session)
    task = session.get(InspectionTask, sc["task_id"])
    assert task is not None
    task.canceled_at = utcnow()
    session.commit()
    resp = client.post(
        _CR, headers=sc["vol_h"],
        json={"assignment_id": sc["assignment_id"], "reason": "任务已取消"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == ErrorCode.STATE_CONFLICT.value


def test_create_duplicate_pending_409(client: TestClient, session: Session) -> None:
    sc = _assigned_volunteer_scene(client, session)
    first = client.post(
        _CR, headers=sc["vol_h"],
        json={"assignment_id": sc["assignment_id"], "reason": "第一次"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        _CR, headers=sc["vol_h"],
        json={"assignment_id": sc["assignment_id"], "reason": "重复待处理"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == ErrorCode.STATE_CONFLICT.value
    session.commit()
    session.expire_all()
    assert _count(session, AssignmentChangeRequest) == 1


# --------------------------------------------------------------------------- #
# 处理：转态 + 无隐式改派 + 重复处理守卫
# --------------------------------------------------------------------------- #
def _created_request(client: TestClient, session: Session) -> dict:
    sc = _assigned_volunteer_scene(client, session)
    r = client.post(
        _CR, headers=sc["vol_h"],
        json={"assignment_id": sc["assignment_id"], "reason": "需调班"},
    )
    assert r.status_code == 200, r.text
    sc["request_id"] = int(r.json()["data"]["id"])
    return sc


def test_review_approve(client: TestClient, session: Session) -> None:
    sc = _created_request(client, session)
    resp = client.post(
        f"{_CR}/{sc['request_id']}/review",
        headers=sc["h"],
        json={"decision": "APPROVED", "comment": "同意，稍后改派"},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["status"] == ChangeRequestStatus.APPROVED.value
    assert d["comment"] == "同意，稍后改派"
    assert d["processed_by"] is not None
    assert d["processed_at"] is not None

    session.commit()
    session.expire_all()
    # 关键不变式：approve 仅迁移申请状态，不改受派人（无隐式改派）。
    a = session.execute(
        select(InspectionAssignment).where(InspectionAssignment.id == sc["assignment_id"])
    ).scalar_one()
    assert a.volunteer_user_id == sc["vol"].id
    assert _audit_actions(session, "assignment.change_request.review") == 1


def test_review_reject(client: TestClient, session: Session) -> None:
    sc = _created_request(client, session)
    resp = client.post(
        f"{_CR}/{sc['request_id']}/review",
        headers=sc["h"],
        json={"decision": "REJECTED", "comment": "人手不足"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == ChangeRequestStatus.REJECTED.value


def test_review_twice_409(client: TestClient, session: Session) -> None:
    sc = _created_request(client, session)
    first = client.post(
        f"{_CR}/{sc['request_id']}/review", headers=sc["h"], json={"decision": "APPROVED"}
    )
    assert first.status_code == 200, first.text
    again = client.post(
        f"{_CR}/{sc['request_id']}/review", headers=sc["h"], json={"decision": "REJECTED"}
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == ErrorCode.STATE_CONFLICT.value


def test_review_missing_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    resp = client.post(
        f"{_CR}/999999/review", headers=h, json={"decision": "APPROVED"}
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# 读取范围
# --------------------------------------------------------------------------- #
def test_list_scoping(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    task2 = _add_second_task(client, h, sc["sem_id"])
    other = _create_admin_class(client, h, "CS2402")
    v1 = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="v1", student_no="V1",
        admin_class_id=other,
    )
    v2 = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="v2", student_no="V2",
        admin_class_id=other,
    )
    _assign(client, h, int(sc["task"]["id"]), v1.id)
    _assign(client, h, int(task2["id"]), v2.id)
    a1 = _assignment_id(session, int(sc["task"]["id"]))
    a2 = _assignment_id(session, int(task2["id"]))
    v1h = _bearer(_login(client, "v1"))
    v2h = _bearer(_login(client, "v2"))
    r1 = client.post(_CR, headers=v1h, json={"assignment_id": a1, "reason": "r1"})
    assert r1.status_code == 200, r1.text
    r2 = client.post(_CR, headers=v2h, json={"assignment_id": a2, "reason": "r2"})
    assert r2.status_code == 200, r2.text

    mine1 = client.get(_ME_CR, headers=v1h).json()["data"]
    assert mine1["total"] == 1
    assert {int(x["request_user_id"]) for x in mine1["items"]} == {v1.id}
    mine2 = client.get(_ME_CR, headers=v2h).json()["data"]
    assert mine2["total"] == 1
    assert {int(x["request_user_id"]) for x in mine2["items"]} == {v2.id}
    mgr = client.get(_CR, headers=h, params={"limit": 50}).json()["data"]
    assert mgr["total"] == 2
    pend = client.get(_CR, headers=h, params={"status": "PENDING", "limit": 50}).json()["data"]
    assert pend["total"] == 2
    done = client.get(_CR, headers=h, params={"status": "APPROVED", "limit": 50}).json()["data"]
    assert done["total"] == 0


# --------------------------------------------------------------------------- #
# 真实 MySQL 并发（同一 PENDING 申请被两连接同时处理 → 恰好一次转态）
# --------------------------------------------------------------------------- #
def _review_worker(
    engine: Engine, actor_id: int, request_id: int, decision: str,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="admin", display_name="admin",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        barrier.wait()
        body = ChangeRequestReviewRequest(decision=decision, comment="concurrency")  # type: ignore[arg-type]
        InspectionService(s).review_change_request(
            actor, request_id, body, request_id_str=f"conc-{idx}"
        )
        out[idx] = ("ok",)
    except ConflictError as exc:
        s.rollback()
        out[idx] = ("conflict", exc.code)
    except AppError as exc:
        s.rollback()
        out[idx] = ("rejected", exc.code)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_review_same_request_one_wins(
    client: TestClient, engine: Engine, session: Session
) -> None:
    sc = _created_request(client, session)
    admin = session.execute(
        select(UserAccount).where(UserAccount.username == "admin")
    ).scalar_one()
    session.commit()  # 结束夹具读事务，令独立会话看到已提交的 PENDING 申请。
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_review_worker,
            args=(engine, admin.id, sc["request_id"], "APPROVED", barrier, out, 0),
        ),
        threading.Thread(
            target=_review_worker,
            args=(engine, admin.id, sc["request_id"], "REJECTED", barrier, out, 1),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(out) == 2, out
    ok_count = sum(1 for r in out.values() if r[0] == "ok")
    conflict_count = sum(1 for r in out.values() if r[0] == "conflict")
    # 恰好一次成功转态，另一次因非 PENDING 被拒（409）。
    assert ok_count == 1, out
    assert conflict_count == 1, out

    session.commit()
    session.expire_all()
    req = session.get(AssignmentChangeRequest, sc["request_id"])
    assert req is not None
    assert req.status in {
        ChangeRequestStatus.APPROVED.value,
        ChangeRequestStatus.REJECTED.value,
    }
    assert req.processed_at is not None
    assert _audit_actions(session, "assignment.change_request.review") == 1
