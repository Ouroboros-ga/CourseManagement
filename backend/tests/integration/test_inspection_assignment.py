"""查课排班与改派（P4 Wave 3a：人工改派 + 自动排班、硬约束、volunteer_day_lock 并发）
集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P4 与技术方案 11.2（硬约束）、15（并发锁层级）：
- 功能守卫：无令牌 401；缺 assignment.manage → 人工 / 自动 403。
- 人工改派 happy：建受派 method=MANUAL、任务 lock_version 前进、审计 assignment.manual_set。
- 硬约束（原因码经 422 fieldErrors.reason_code 回显）：
  NOT_VOLUNTEER / NO_QUALIFICATION / SELF_CLASS_AVOID / OWN_CLASS_CONFLICT / TASK_TIME_CONFLICT。
- 版本不符 409 VERSION_CONFLICT；已取消任务 409 STATE_CONFLICT。
- 改派到不同志愿者：新旧日期锚点均加锁，受派改写、任务版本再前进、审计 before 记录原受派。
- 自动排班：贪心 + 锁内重验；全池/子集、本班回避排除、批内时段冲突排除、单日上限软约束。
- 真实 MySQL 并发：两连接对同一志愿者同日重叠任务改派 → 恰好一条落库、另一条被拒。
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    AssignMethod,
    InspectionAssignment,
    InspectionTask,
    VolunteerDayLock,
)
from app.modules.inspection.schemas import (
    REASON_DAY_CAP,
    REASON_NO_QUALIFICATION,
    REASON_NOT_VOLUNTEER,
    REASON_OWN_CLASS,
    REASON_SELF_CLASS,
    REASON_TASK_CONFLICT,
    AssignmentSetRequest,
)
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
_AUTO = "/api/v1/assignments/auto"
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


def _create_student(
    client: TestClient, h: dict[str, str], no: str, class_id: int
) -> int:
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
    """建绑定学生 + （可选）VOLUNTEER 角色 +（可选）学期资格的账号。"""
    sid = _create_student(client, h, student_no, admin_class_id)
    roles = [RoleCode.VOLUNTEER.value] if volunteer else [RoleCode.STUDENT.value]
    acct = _make_user(session, username, roles, student_id=sid)
    if qualify:
        _grant_qual(client, h, sem_id, sid)
    return acct


def _one_task_scene(client: TestClient, h: dict[str, str]) -> dict:
    """ACTIVE 学期 + 被查行政班 CS2401（S001/S002）+ 教学班 T1 + 周一 1-2 节课表，生成 1 个任务。"""
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
    return {
        "sem_id": sem_id,
        "cs2401": cs2401,
        "course": course,
        "task": tasks[0],
    }


def _count(session: Session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def _audit_actions(session: Session, action: str) -> int:
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


def _reason_code(resp) -> str:
    return resp.json()["fieldErrors"]["reason_code"]


# --------------------------------------------------------------------------- #
# 认证与功能守卫
# --------------------------------------------------------------------------- #
def test_assignment_requires_auth_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    put = client.put(
        f"{_TASKS}/1/assignment", json={"volunteer_user_id": 1, "lock_version": 0}
    )
    assert put.status_code == 401
    assert client.post(_AUTO, json={"semester_id": 1, "task_ids": [1]}).status_code == 401


def test_missing_assign_permission_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="vol", student_no="V001",
        admin_class_id=_create_admin_class(client, h, "CS2402"),
    )
    # 仅 inspection.read：无人工 / 自动排班权限。
    _make_perm_user(session, "reader", [PermissionCode.INSPECTION_READ.value])
    rh = _bearer(_login(client, "reader"))
    task_id = int(sc["task"]["id"])
    put = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=rh,
        json={"volunteer_user_id": vol.id, "lock_version": 0},
    )
    assert put.status_code == 403, put.text
    auto = client.post(_AUTO, headers=rh, json={"semester_id": sc["sem_id"], "task_ids": [task_id]})
    assert auto.status_code == 403, auto.text


# --------------------------------------------------------------------------- #
# 人工改派：happy + 硬约束
# --------------------------------------------------------------------------- #
def test_manual_assign_happy_path(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="volA", student_no="VA1",
        admin_class_id=other,
    )
    task_id = int(sc["task"]["id"])
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 0, "reason": "指定志愿者"},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["lock_version"] == 1
    assert d["assignment"] is not None
    assert int(d["assignment"]["volunteer_user_id"]) == vol.id
    assert d["assignment"]["assign_method"] == AssignMethod.MANUAL.value

    session.expire_all()
    a = session.execute(select(InspectionAssignment)).scalar_one()
    assert a.assign_method == AssignMethod.MANUAL.value
    assert a.assigned_by is not None
    task = session.get(InspectionTask, task_id)
    assert task is not None and task.lock_version == 1
    assert _audit_actions(session, "assignment.manual_set") == 1


def test_manual_not_volunteer_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    # 绑定学生但非 VOLUNTEER 角色（且不发资格，否则发资格会自动补授 VOLUNTEER）。
    plain = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="plain", student_no="P001",
        admin_class_id=other, volunteer=False, qualify=False,
    )
    resp = client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": plain.id, "lock_version": 0},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == ErrorCode.VALIDATION_ERROR.value
    assert _reason_code(resp) == REASON_NOT_VOLUNTEER


def test_manual_no_qualification_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="noqual", student_no="NQ1",
        admin_class_id=other, qualify=False,
    )
    resp = client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 0},
    )
    assert resp.status_code == 422, resp.text
    assert _reason_code(resp) == REASON_NO_QUALIFICATION


def test_manual_self_class_avoid_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 志愿者学生属被查行政班 CS2401 → 本班回避。
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="selfc", student_no="SC1",
        admin_class_id=sc["cs2401"],
    )
    resp = client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 0},
    )
    assert resp.status_code == 422, resp.text
    assert _reason_code(resp) == REASON_SELF_CLASS


def test_manual_own_class_conflict_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 志愿者属其它行政班（不触发本班回避），但本人周一第 1 周 1-2 节有课 → 课表时段冲突。
    other = _create_admin_class(client, h, "CS2402")
    course = _create_course(client, h, "C900")
    tc_own = _create_tc(client, h, sc["sem_id"], course, "TOWN")
    own_student = _create_student(client, h, "OWN1", other)
    _enroll(client, h, tc_own, [own_student])
    _schedule(client, h, tc_own, 1, 2, "B202")
    _grant_qual(client, h, sc["sem_id"], own_student)
    acct = _make_user(session, "ownv", [RoleCode.VOLUNTEER.value], student_id=own_student)
    resp = client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": acct.id, "lock_version": 0},
    )
    assert resp.status_code == 422, resp.text
    assert _reason_code(resp) == REASON_OWN_CLASS


def test_manual_task_time_conflict_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 再建同日 2-3 节重叠任务（含第 2 节，与 1-2 重叠）。
    course = _create_course(client, h, "C800")
    t2 = _create_tc(client, h, sc["sem_id"], course, "T2")
    _enroll(
        client, h, t2,
        [_create_student(client, h, "S201", _create_admin_class(client, h, "CS3301"))],
    )
    _schedule(client, h, t2, 2, 3, "A102")
    assert _gen_course(client, h, sc["sem_id"], [t2]) == 1
    tasks = _list_tasks(client, h, sc["sem_id"])
    task1 = next(t for t in tasks if t["start_period"] == 1)
    task2 = next(t for t in tasks if t["start_period"] == 2)
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="confv", student_no="CV1",
        admin_class_id=other,
    )
    ok = client.put(
        f"{_TASKS}/{int(task1['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 0},
    )
    assert ok.status_code == 200, ok.text
    clash = client.put(
        f"{_TASKS}/{int(task2['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": int(task2["lock_version"])},
    )
    assert clash.status_code == 422, clash.text
    assert _reason_code(clash) == REASON_TASK_CONFLICT


def test_manual_version_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="verv", student_no="VV1",
        admin_class_id=other,
    )
    resp = client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 99},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == ErrorCode.VERSION_CONFLICT.value


def test_manual_canceled_task_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    task_id = int(sc["task"]["id"])
    # 直接置任务为已取消（取消端点属 Wave 3c），改派应被状态守卫拒绝。
    from app.core.database import utcnow
    task = session.get(InspectionTask, task_id)
    assert task is not None
    task.canceled_at = utcnow()
    session.commit()
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="cancelv", student_no="CX1",
        admin_class_id=other,
    )
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": int(sc["task"]["lock_version"])},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == ErrorCode.STATE_CONFLICT.value


def test_manual_reassign_switches_volunteer(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    v1 = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="v1", student_no="V1A",
        admin_class_id=other,
    )
    v2 = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="v2", student_no="V2A",
        admin_class_id=other,
    )
    task_id = int(sc["task"]["id"])
    first = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": v1.id, "lock_version": 0},
    )
    assert first.status_code == 200, first.text
    # 改派给 v2：新旧日期锚点都应被加锁（可事后校验两锚点均已建立）。
    second = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": v2.id, "lock_version": 1, "reason": "换人"},
    )
    assert second.status_code == 200, second.text
    d = second.json()["data"]
    assert int(d["assignment"]["volunteer_user_id"]) == v2.id
    assert d["lock_version"] == 2

    session.expire_all()
    a = session.execute(select(InspectionAssignment)).scalar_one()
    assert a.volunteer_user_id == v2.id
    assert a.lock_version == 1  # 既有受派被改写而非新建
    # 两名志愿者的当日锚点都存在。
    anchors = session.execute(
        select(VolunteerDayLock).where(VolunteerDayLock.inspection_date == date(2026, 9, 7))
    ).scalars().all()
    assert {x.volunteer_user_id for x in anchors} == {v1.id, v2.id}


# --------------------------------------------------------------------------- #
# 自动排班
# --------------------------------------------------------------------------- #
def test_auto_uses_semester_load_across_dates(client: TestClient, session: Session) -> None:
    from datetime import timedelta

    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "BALANCE")
    volunteers = [
        _make_volunteer(client, h, session, sem_id=sc["sem_id"], username=f"balance{i}",
                        student_no=f"BAL{i}", admin_class_id=other)
        for i in range(2)
    ]
    original = session.get(InspectionTask, int(sc["task"]["id"]))
    ids = [original.id]
    for i in range(1, 4):
        clone = InspectionTask(
            task_key=f"balance:{i}", semester_id=original.semester_id,
            inspection_date=original.inspection_date + timedelta(days=i),
            week_no=1, inspection_type="COURSE", start_period=1, end_period=2,
            roster_version=1, expected_count_snapshot=0, expected_count_current=0,
            require_photo_snapshot=False,
        )
        session.add(clone)
        session.flush()
        ids.append(clone.id)
    session.commit()
    # 分两次请求，第二次必须计入第一次已落库的学期负载。
    from app.modules.academic.models import Semester
    from app.modules.inspection.scheduling.loader import load_snapshot
    from sqlalchemy import event

    sem = session.get(Semester, sc["sem_id"])
    targets = list(session.scalars(select(InspectionTask).where(InspectionTask.id.in_(ids))))
    statements = []

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", record_sql)
    try:
        load_snapshot(session, sem, targets[:1], [v.id for v in volunteers])
        single_count = len(statements)
        statements.clear()
        load_snapshot(session, sem, targets, [v.id for v in volunteers])
        assert len(statements) == single_count
        assert single_count <= 10
    finally:
        event.remove(session.bind, "before_cursor_execute", record_sql)

    owners = []
    for batch in [ids[:2], ids[2:]]:
        resp = client.post(_AUTO, headers=h,
                           json={"semester_id": sc["sem_id"], "task_ids": batch})
        assert resp.status_code == 200, resp.text
        owners.extend(int(row["volunteer_user_id"]) for row in resp.json()["data"]["assigned"])
    assert owners.count(volunteers[0].id) == 2
    assert owners.count(volunteers[1].id) == 2


def test_auto_excludes_disabled_student(client: TestClient, session: Session) -> None:
    from app.modules.academic.models import Student

    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "DISABLED")
    vol = _make_volunteer(client, h, session, sem_id=sc["sem_id"], username="disabled",
                          student_no="DIS1", admin_class_id=other)
    session.get(Student, vol.student_id).status = "DISABLED"
    session.commit()
    resp = client.post(_AUTO, headers=h, json={"semester_id": sc["sem_id"],
                        "task_ids": [int(sc["task"]["id"])], "candidate_user_ids": [vol.id]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["assigned_count"] == 0


def test_auto_loads_fresh_counts_after_prior_repeatable_read(
    client: TestClient, session: Session, engine: Engine,
) -> None:
    from datetime import timedelta

    from app.modules.inspection.schemas import AutoAssignRequest

    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "FRESH")
    volunteers = [
        _make_volunteer(client, h, session, sem_id=sc["sem_id"], username=f"fresh{i}",
                        student_no=f"FRESH{i}", admin_class_id=other)
        for i in range(2)
    ]
    admin = session.execute(select(UserAccount).where(UserAccount.username == "admin")).scalar_one()
    actor = CurrentUser(admin.id, admin.username, admin.display_name, admin.status, [], [])
    next_task = InspectionTask(
        task_key="fresh:next", semester_id=sc["sem_id"],
        inspection_date=date(2026, 9, 7) + timedelta(days=1), week_no=1,
        inspection_type="COURSE", start_period=1, end_period=2,
        roster_version=1, expected_count_snapshot=0, expected_count_current=0,
        require_photo_snapshot=False,
    )
    session.add(next_task)
    session.commit()
    ids = [v.id for v in volunteers]
    next_id = next_task.id
    session.commit()
    # 模拟请求鉴权已建立 RR 快照；另一个请求随后提交受派。
    assert session.scalar(select(func.count()).select_from(InspectionAssignment)) == 0
    with Session(engine) as writer:
        writer.add(InspectionAssignment(task_id=int(sc["task"]["id"]),
                   volunteer_user_id=ids[0], assign_method="AUTO", assigned_by=actor.id))
        writer.commit()
    result = InspectionService(session).auto_assign(
        actor, AutoAssignRequest(semester_id=sc["sem_id"], task_ids=[next_id]), None)
    assert int(result.assigned[0].volunteer_user_id) == ids[1]


def test_auto_with_single_connection_business_pool(
    client: TestClient, session: Session, engine: Engine,
) -> None:
    from app.modules.inspection.schemas import AutoAssignRequest
    from sqlalchemy import create_engine

    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "POOL1")
    vol = _make_volunteer(client, h, session, sem_id=sc["sem_id"],
                          username="pool1", student_no="POOL1", admin_class_id=other)
    admin = session.execute(select(UserAccount).where(UserAccount.username == "admin")).scalar_one()
    actor = CurrentUser(admin.id, admin.username, admin.display_name, admin.status, [], [])
    one = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=1)
    try:
        with Session(one) as request_session:
            result = InspectionService(request_session).auto_assign(
                actor, AutoAssignRequest(semester_id=sc["sem_id"],
                                         task_ids=[int(sc["task"]["id"])]), None)
        assert int(result.assigned[0].volunteer_user_id) == vol.id
    finally:
        one.dispose()


def test_auto_final_conflict_rolls_back_whole_plan(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "ROLLBACK")
    _make_volunteer(client, h, session, sem_id=sc["sem_id"], username="rollback",
                    student_no="ROLL1", admin_class_id=other)
    clone = InspectionTask(
        task_key="rollback:next", semester_id=sc["sem_id"], inspection_date=date(2026, 9, 8),
        week_no=1, inspection_type="COURSE", start_period=1, end_period=2,
        roster_version=1, expected_count_snapshot=0, expected_count_current=0,
        require_photo_snapshot=False,
    )
    session.add(clone)
    session.commit()
    from dataclasses import replace

    import app.modules.inspection.service as service_module

    original = service_module.load_snapshot

    def qualification_changed(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        if kwargs.get("lock_inputs"):
            # 模拟锁内当前读发现后一个任务的资格变化；整批不应有任何部分写入。
            snapshot.tasks[-1] = replace(snapshot.tasks[-1], candidates=frozenset())
        return snapshot

    monkeypatch.setattr(service_module, "load_snapshot", qualification_changed)
    resp = client.post(_AUTO, headers=h, json={"semester_id": sc["sem_id"],
                        "task_ids": [int(sc["task"]["id"]), clone.id]})
    assert resp.status_code == 409, resp.text
    session.rollback()
    assert _count(session, InspectionAssignment) == 0
    assert _audit_actions(session, "assignment.auto_run") == 0


def test_auto_assign_full_pool(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    other = _create_admin_class(client, h, "CS2402")
    v1 = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="av1", student_no="AV1",
        admin_class_id=other,
    )
    _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="av2", student_no="AV2",
        admin_class_id=other,
    )
    resp = client.post(
        _AUTO,
        headers=h,
        json={"semester_id": sc["sem_id"], "inspection_date": _MON1, "reason": "自动排班"},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["target_task_count"] == 1
    assert d["assigned_count"] == 1
    assert d["unassigned_count"] == 0
    # 贪心取升序首个合格志愿者（v1）。
    assert int(d["assigned"][0]["volunteer_user_id"]) == v1.id

    session.expire_all()
    a = session.execute(select(InspectionAssignment)).scalar_one()
    assert a.assign_method == AssignMethod.AUTO.value
    assert _audit_actions(session, "assignment.auto_run") == 1


def test_auto_excludes_self_class(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 候选池仅一名本班回避志愿者 → 无合格志愿者落单。
    selfvol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="sv", student_no="SV1",
        admin_class_id=sc["cs2401"],
    )
    resp = client.post(
        _AUTO,
        headers=h,
        json={"semester_id": sc["sem_id"], "task_ids": [int(sc["task"]["id"])],
              "candidate_user_ids": [selfvol.id]},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["assigned_count"] == 0
    assert d["unassigned_count"] == 1
    assert d["unassigned"][0]["reason_code"] == REASON_SELF_CLASS
    session.expire_all()
    assert _count(session, InspectionAssignment) == 0


def test_auto_in_batch_time_conflict(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 再造一个同日重叠任务（2-3 节，与 1-2 重叠）。
    course = _create_course(client, h, "C800")
    t2 = _create_tc(client, h, sc["sem_id"], course, "T2")
    _enroll(
        client, h, t2,
        [_create_student(client, h, "S201", _create_admin_class(client, h, "CS3301"))],
    )
    _schedule(client, h, t2, 2, 3, "A102")
    assert _gen_course(client, h, sc["sem_id"], [t2]) == 1
    other = _create_admin_class(client, h, "CS2402")
    # 仅一名志愿者，两重叠任务 → 批内只有一个能给他，另一个因时段冲突落单。
    _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="onev", student_no="OV1",
        admin_class_id=other,
    )
    resp = client.post(
        _AUTO,
        headers=h,
        json={"semester_id": sc["sem_id"], "inspection_date": _MON1},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["target_task_count"] == 2
    assert d["assigned_count"] == 1
    assert d["unassigned_count"] == 1
    assert d["unassigned"][0]["reason_code"] == REASON_TASK_CONFLICT


def test_auto_day_cap_soft_constraint(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 同日再建一个不重叠任务（8-9 节）。
    course = _create_course(client, h, "C700")
    t2 = _create_tc(client, h, sc["sem_id"], course, "T2")
    _enroll(
        client, h, t2,
        [_create_student(client, h, "S201", _create_admin_class(client, h, "CS3301"))],
    )
    _schedule(client, h, t2, 8, 9, "A103")
    assert _gen_course(client, h, sc["sem_id"], [t2]) == 1
    other = _create_admin_class(client, h, "CS2402")
    _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="capv", student_no="CP1",
        admin_class_id=other,
    )
    monkeypatch.setenv("ASSIGNMENT_MAX_TASKS_PER_DAY", "1")
    get_settings.cache_clear()
    try:
        resp = client.post(
            _AUTO,
            headers=h,
            json={"semester_id": sc["sem_id"], "inspection_date": _MON1},
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["target_task_count"] == 2
        assert d["assigned_count"] == 1
        assert d["unassigned_count"] == 1
        assert d["unassigned"][0]["reason_code"] == REASON_DAY_CAP
    finally:
        monkeypatch.delenv("ASSIGNMENT_MAX_TASKS_PER_DAY", raising=False)
        get_settings.cache_clear()


def test_auto_no_targets_returns_zero(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 已分配后再次自动排班：范围内无未分配任务。
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="pre", student_no="PRE",
        admin_class_id=other,
    )
    client.put(
        f"{_TASKS}/{int(sc['task']['id'])}/assignment",
        headers=h,
        json={"volunteer_user_id": vol.id, "lock_version": 0},
    )
    resp = client.post(
        _AUTO,
        headers=h,
        json={"semester_id": sc["sem_id"], "inspection_date": _MON1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["target_task_count"] == 0
    assert resp.json()["data"]["assigned_count"] == 0


# --------------------------------------------------------------------------- #
# 真实 MySQL 并发（技术方案 15：同日重叠改派串行化，恰好一条落库）
# --------------------------------------------------------------------------- #
def _assign_worker(
    engine: Engine, actor_id: int, task_id: int, vol_id: int, version: int,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    """独立连接直调服务层，绕开 HTTP 线程安全问题（与 RBAC 并发测试同款写法）。"""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="admin", display_name="admin",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        barrier.wait()
        body = AssignmentSetRequest(
            volunteer_user_id=vol_id, lock_version=version, reason="concurrency"
        )
        InspectionService(s).assign_manual(actor, task_id, body, request_id=f"conc-{idx}")
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


def test_concurrent_same_volunteer_overlapping_day_one_wins(
    client: TestClient, engine: Engine, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _one_task_scene(client, h)
    # 同日再造一个重叠任务：1-2 节与 2-3 节在第 2 节相交。
    course2 = _create_course(client, h, "C800")
    tc2 = _create_tc(client, h, sc["sem_id"], course2, "T2")
    other_roster = _create_admin_class(client, h, "CS3301")
    _enroll(client, h, tc2, [_create_student(client, h, "S201", other_roster)])
    _schedule(client, h, tc2, 2, 3, "B101")
    assert _gen_course(client, h, sc["sem_id"], [tc2]) == 1
    session.commit()  # 释放夹具读视图，令随后独立会话看到已提交任务。

    # 唯一志愿者（行政班与被查名单无关，本人无课，已具资格）。
    other = _create_admin_class(client, h, "CS2402")
    vol = _make_volunteer(
        client, h, session, sem_id=sc["sem_id"], username="volX", student_no="VX1",
        admin_class_id=other,
    )
    admin = session.execute(
        select(UserAccount).where(UserAccount.username == "admin")
    ).scalar_one()
    task_ids = sorted(int(t["id"]) for t in _list_tasks(client, h, sc["sem_id"]))
    assert len(task_ids) == 2

    barrier: threading.Barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_assign_worker,
            args=(engine, admin.id, tid, vol.id, 0, barrier, out, i),
        )
        for i, tid in enumerate(task_ids)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(out) == 2, out
    # 至多一名成功：另一名被志愿者日期锚点串行化后在锁内重验拒绝
    # （时段冲突 VALIDATION_ERROR / 版本竞态 VERSION_CONFLICT / 死锁回滚 error 均可接受）。
    ok_count = sum(1 for r in out.values() if r[0] == "ok")
    assert ok_count <= 1, out

    # 结束夹具会话此前的读事务，取新快照以看到独立连接 worker 的提交。
    session.commit()
    session.expire_all()
    committed = session.execute(
        select(InspectionAssignment).where(InspectionAssignment.volunteer_user_id == vol.id)
    ).scalars().all()
    # 核心不变式：同一志愿者、同日重叠时段，恰好一条受派落库（既不双分也不丢分）。
    assert len(committed) == 1, out
