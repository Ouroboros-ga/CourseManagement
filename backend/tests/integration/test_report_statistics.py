"""统计域 P7(W7a)：只读考勤统计与未完成清单，连真实 MySQL。

覆盖技术方案 17 与 PERMISSIONS.md 5/6.2/7：
- 鉴权与门禁：无令牌 401；负责人默认 statistics.read 关 → 403；开启可选后可读；学生无 → 403。
- 口径一：仅统计审核通过且未取消任务；待审核异常不计入正式缺勤。
- 口径二：分母（有效应到）≤0 → statistics_available=false 且比率 null（不显示 0%/100%）。
- 口径三：先累加分子分母再相除，不对各班百分比简单平均（多任务/多班聚合校验）。
- 口径四：班级按名单快照归并；人工只调总数任务班级分母不可靠 → class_ratio_available=false
  并计入 excluded_task_count，不均摊。
- 口径五：「当前未完成」与「截止时未完成」分别输出、不混名；CANCELED 排除。
- 查询校验：week_no 与 date_from/date_to 互斥、必选其一 → 422。
"""

from __future__ import annotations

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
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"
_SUBS = "/api/v1/submissions"
_STATS_ATT = "/api/v1/statistics/attendance"
_STATS_INC = "/api/v1/statistics/incomplete-tasks"
_SETTLE = "/api/v1/submission-deadlines/settle"
_MON1 = "2026-09-07"
_MON1_D = date_(2026, 9, 7)
_MON2_D = date_(2026, 9, 14)


# --------------------------------------------------------------------------- #
# 装配助手（与 test_objection 同构，令本文件自包含）
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


def _put(client: TestClient, h: dict[str, str], url: str, body: dict) -> dict:
    resp = client.put(url, headers=h, json=body)
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


def _enroll(client: TestClient, h: dict[str, str], tc_id: int, sids: list[int]) -> None:
    rp = client.put(
        f"{_ACA}/teaching-classes/{tc_id}/students",
        headers=h,
        json={"student_ids": sids},
    )
    assert rp.status_code == 200, rp.text


def _schedule(
    client: TestClient, h: dict[str, str], tc_id: int, start: int, end: int, room: str, week: int
) -> int:
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


def _gen_course(
    client: TestClient, h: dict[str, str], sem_id: int, tc_ids: list[int], weeks: list[int]
) -> int:
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


def _grant_qual(client: TestClient, h: dict[str, str], sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={
            "semester_id": sem_id,
            "student_id": student_id,
            "enabled": True,
            "reason": "合格",
        },
    )
    assert rp.status_code == 200, rp.text


def _assign(
    client: TestClient, h: dict[str, str], session: Session, task_id: int, vol_id: int
) -> None:
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol_id, "lock_version": _task_lock_version(session, task_id)},
    )
    assert resp.status_code == 200, resp.text


def _setup_sem(client: TestClient, h: dict[str, str]) -> int:
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
    return int(sem["id"])


def _make_volunteer_for_task(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    sem_id: int,
    task_id: int,
    username: str,
) -> dict[str, str]:
    other = _create_admin_class(client, h, f"VCLASS_{username}")
    sid = _create_student(client, h, f"V{username}", other)
    _grant_qual(client, h, sem_id, sid)
    vol = _make_user(session, username, [RoleCode.VOLUNTEER.value], student_id=sid)
    _assign(client, h, session, task_id, vol.id)
    return _bearer(_login(client, username))


def _deadline_day(session: Session, sem_id: int, on_date: date_) -> SubmissionDeadlineDay:
    session.commit()
    session.expire_all()
    return session.execute(
        select(SubmissionDeadlineDay).where(
            SubmissionDeadlineDay.semester_id == sem_id,
            SubmissionDeadlineDay.inspection_date == on_date,
        )
    ).scalar_one()


def _set_future_deadline(session: Session, sem_id: int, on_date: date_) -> None:
    day = _deadline_day(session, sem_id, on_date)
    day.deadline_at = utcnow() + timedelta(hours=48)
    session.commit()


def _approve_abnormal(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    sem_id: int,
    task_id: int,
    items: list[dict],
) -> int:
    _set_future_deadline(session, sem_id, _MON1_D)
    vh = _make_volunteer_for_task(client, h, session, sem_id, task_id, f"vol{task_id}")
    body = {"result": "ABNORMAL", "abnormal_items": items, "file_ids": []}
    r = client.post(f"{_TASKS}/{task_id}/submissions", headers=vh, json=body)
    assert r.status_code == 200, r.text
    sub_id = int(r.json()["data"]["id"])
    assert (
        client.post(
            f"{_SUBS}/{sub_id}/review", headers=h, json={"decision": "APPROVED"}
        ).status_code
        == 200
    )
    return sub_id


def _pending_only(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    sem_id: int,
    task_id: int,
    items: list[dict],
) -> int:
    _set_future_deadline(session, sem_id, _MON1_D)
    vh = _make_volunteer_for_task(client, h, session, sem_id, task_id, f"volp{task_id}")
    body = {"result": "ABNORMAL", "abnormal_items": items, "file_ids": []}
    r = client.post(f"{_TASKS}/{task_id}/submissions", headers=vh, json=body)
    assert r.status_code == 200, r.text
    return int(r.json()["data"]["id"])


def _approve_normal(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    sem_id: int,
    task_id: int,
) -> int:
    """NORMAL 结论提交并通过审核：任务变为"符合条件"（有 APPROVED 提交）但异常数为 0。"""
    _set_future_deadline(session, sem_id, _MON1_D)
    vh = _make_volunteer_for_task(client, h, session, sem_id, task_id, f"voln{task_id}")
    body = {"result": "NORMAL", "abnormal_items": [], "file_ids": []}
    r = client.post(f"{_TASKS}/{task_id}/submissions", headers=vh, json=body)
    assert r.status_code == 200, r.text
    sub_id = int(r.json()["data"]["id"])
    assert (
        client.post(
            f"{_SUBS}/{sub_id}/review", headers=h, json={"decision": "APPROVED"}
        ).status_code
        == 200
    )
    return sub_id


def _scene2(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    *,
    extra_class: bool = False,
    two_tasks: bool = False,
) -> dict:
    """基础场景：学期 2026FA + 行政班 CS2401(s1,s2) + 教学班 T1(week1)。

    extra_class：另建 CS2402(s3) 并入 T1（跨行政班，测班级归并）。
    two_tasks：另建 T2(s4,s5,CS2403) week2（测跨任务先累加再相除）。
    """
    sem_id = _setup_sem(client, h)
    cs = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs)
    s2 = _create_student(client, h, "S002", cs)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    enrolled = [s1, s2]
    s3 = None
    if extra_class:
        cs2 = _create_admin_class(client, h, "CS2402")
        s3 = _create_student(client, h, "S003", cs2)
        enrolled.append(s3)
    _enroll(client, h, t1, enrolled)
    _schedule(client, h, t1, 1, 2, "A101", 1)
    assert _gen_course(client, h, sem_id, [t1], [1]) == 1

    t2 = s4 = s5 = None
    if two_tasks:
        cs3 = _create_admin_class(client, h, "CS2403")
        s4 = _create_student(client, h, "S004", cs3)
        s5 = _create_student(client, h, "S005", cs3)
        t2 = _create_tc(client, h, sem_id, course, "T2")
        _enroll(client, h, t2, [s4, s5])
        _schedule(client, h, t2, 1, 2, "B201", 2)
        assert _gen_course(client, h, sem_id, [t2], [2]) == 1

    tasks = _list_tasks(client, h, sem_id)
    by_week = {int(t["week_no"]): int(t["id"]) for t in tasks}
    out = {
        "sem_id": sem_id,
        "cs": cs,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "course": course,
        "t1": t1,
        "t2": t2,
        "s4": s4,
        "s5": s5,
        "task_w1": by_week.get(1),
        "task_w2": by_week.get(2),
    }
    return out


def _task_lock_version(session: Session, task_id: int) -> int:
    session.commit()
    session.expire_all()
    row = session.get(InspectionTask, task_id)
    assert row is not None
    return int(row.lock_version)


def _stats(client: TestClient, h: dict[str, str], params: dict) -> dict:
    resp = client.get(_STATS_ATT, headers=h, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# --------------------------------------------------------------------------- #
# 鉴权 / 门禁 / 范围
# --------------------------------------------------------------------------- #
def test_statistics_requires_auth_401(client: TestClient) -> None:
    r = client.get(_STATS_ATT, params={"semester_id": 1, "week_no": 1})
    assert r.status_code == 401, r.text


def test_super_admin_can_read(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    assert data["eligible_task_count"] == 1


def test_sam_denied_without_optional(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam_h = _bearer(_login(client, "sam"))
    r = client.get(_STATS_ATT, headers=sam_h, params={"semester_id": sc["sem_id"], "week_no": 1})
    assert r.status_code == 403, r.text


def test_sam_reads_after_optional_enabled(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    sam = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    _put(
        client,
        h,
        f"/api/v1/users/{sam.id}/optional-permissions/statistics.read",
        {"enabled": True, "lockVersion": sam.lock_version, "reason": "兼看统计"},
    )
    sam_h2 = _bearer(_login(client, "sam"))
    r = client.get(_STATS_ATT, headers=sam_h2, params={"semester_id": sc["sem_id"], "week_no": 1})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["overall"]["abnormal_count"] == 1


def test_student_denied_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _make_user(session, "stu1", [RoleCode.STUDENT.value], student_id=sc["s1"])
    sh = _bearer(_login(client, "stu1"))
    r = client.get(_STATS_ATT, headers=sh, params={"semester_id": sc["sem_id"], "week_no": 1})
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# 口径一：仅审核通过 + 未取消；待审核异常不计正式缺勤
# --------------------------------------------------------------------------- #
def test_basic_abnormal_counts(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    ov = data["overall"]
    assert data["eligible_task_count"] == 1
    assert ov["expected_count"] == 2
    assert ov["late_count"] == 1
    assert ov["normal_count"] == 1
    assert ov["abnormal_count"] == 1
    assert ov["statistics_available"] is True
    assert abs(ov["abnormal_rate"] - 0.5) < 1e-9


def test_pending_submission_not_counted(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _pending_only(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    assert data["eligible_task_count"] == 0
    assert data["overall"]["expected_count"] == 0
    assert data["overall"]["statistics_available"] is False
    assert data["overall"]["abnormal_rate"] is None


# --------------------------------------------------------------------------- #
# 口径二：分母≤0 → available=false 且比率 null
# --------------------------------------------------------------------------- #
def test_denominator_zero_yields_null_rate(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    # 存在审核通过的 NORMAL 任务（eligible），异常数为 0；再把当前应到人工归零 → 分母=0。
    _approve_normal(client, h, session, sc["sem_id"], sc["task_w1"])
    _patch(
        client,
        h,
        f"{_TASKS}/{sc['task_w1']}/expected-count",
        {
            "expected_count_current": 0,
            "reason": "复核后该课实到 0 人",
            "lock_version": _task_lock_version(session, sc["task_w1"]),
        },
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    assert data["eligible_task_count"] == 1  # 确有符合条件任务，非"无数据"
    assert data["overall"]["expected_count"] == 0  # 分母归零
    # 分母≤0 → 不可用，比率置 null，绝不以 0%/100% 冒充（技术方案 17 第 552 行）
    assert data["overall"]["statistics_available"] is False
    assert data["overall"]["abnormal_rate"] is None


# --------------------------------------------------------------------------- #
# 口径四：人工只调总数 → 班级比例不可靠，不均摊
# --------------------------------------------------------------------------- #
def test_manual_adjustment_excludes_class_ratio(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    _patch(
        client,
        h,
        f"{_TASKS}/{sc['task_w1']}/expected-count",
        {
            "expected_count_current": 1,
            "reason": "复核人数",
            "lock_version": _task_lock_version(session, sc["task_w1"]),
        },
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    cls = {c["class_name"]: c for c in data["classes"]}
    b = cls["班CS2401"]
    assert b["class_ratio_available"] is False
    assert b["excluded_task_count"] == 1


# --------------------------------------------------------------------------- #
# 口径三：跨班级 / 跨任务先累加分子分母再相除
# --------------------------------------------------------------------------- #
def test_multi_class_sum_before_divide(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session, extra_class=True)
    # s1(LATE) 属 CS2401，s3(NORMAL) 属 CS2402
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _stats(client, h, {"semester_id": sc["sem_id"], "week_no": 1})
    ov = data["overall"]
    assert ov["expected_count"] == 3  # 全班 3 人
    assert ov["abnormal_count"] == 1
    cls = {c["class_name"]: c for c in data["classes"]}
    assert cls["班CS2401"]["expected_count"] == 2
    assert cls["班CS2401"]["abnormal_count"] == 1
    assert cls["班CS2402"]["expected_count"] == 1
    assert cls["班CS2402"]["abnormal_count"] == 0
    # 整体先累加再相除=1/3，非各班比率(0.5 与 0)的平均 0.25
    assert abs(ov["abnormal_rate"] - 1 / 3) < 1e-9


def test_multi_task_sum_before_divide(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session, two_tasks=True)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w2"],
        [{"student_id": sc["s4"], "attendance_type": "ABSENT", "note": "缺勤"}],
    )
    data = _stats(
        client,
        h,
        {"semester_id": sc["sem_id"], "date_from": "2026-09-01", "date_to": "2026-09-30"},
    )
    ov = data["overall"]
    assert data["eligible_task_count"] == 2
    assert ov["expected_count"] == 4  # 每任务 2 人
    assert ov["abnormal_count"] == 2  # 1 LATE + 1 ABSENT
    assert abs(ov["abnormal_rate"] - 0.5) < 1e-9


# --------------------------------------------------------------------------- #
# 未完成清单：当前未完成 vs 截止时未完成，两指标不混名；CANCELED 排除
# --------------------------------------------------------------------------- #
def test_overdue_and_current_incomplete_distinct(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session, two_tasks=True)
    # task_w1(week1)：审核通过（有 APPROVED 提交）→ 当前已完成；
    # 其截止仍在未来且不结算 → 无截止快照。
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    # task_w2(week2)：无提交 + 回拨其截止至过去 + 仅结算该日 → OVERDUE_UNEXECUTED 且当前未完成。
    day2 = _deadline_day(session, sc["sem_id"], _MON2_D)
    day2.deadline_at = utcnow() - timedelta(hours=1)
    session.commit()
    _post(
        client,
        h,
        _SETTLE,
        {"semester_id": sc["sem_id"], "inspection_date": _MON2_D.isoformat()},
    )

    resp = client.get(
        _STATS_INC,
        headers=h,
        params={
            "semester_id": sc["sem_id"],
            "date_from": _MON1_D.isoformat(),
            "date_to": _MON2_D.isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    by_task = {int(it["task_id"]): it for it in data["items"]}
    t1 = by_task[sc["task_w1"]]
    t2 = by_task[sc["task_w2"]]
    # 两轴独立：task_w1 已完成（非未完成）且未到期（无截止快照）。
    assert t1["current_incomplete"] is False
    assert t1["deadline_assessment"] is None
    # task_w2 既"当前未完成"又"截止时未完成(OVERDUE_UNEXECUTED)"，两指标同时成立但含义不同。
    assert t2["current_incomplete"] is True
    assert t2["deadline_assessment"] == "OVERDUE_UNEXECUTED"
    # 汇总两口径各 1，互不混用。
    assert data["current_incomplete_count"] == 1
    assert data["overdue_unexecuted_count"] == 1


def test_cancelled_excluded_from_incomplete(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    _post(
        client,
        h,
        f"{_TASKS}/{sc['task_w1']}/cancel",
        {"reason": "停课", "lock_version": _task_lock_version(session, sc["task_w1"])},
    )
    resp = client.get(_STATS_INC, headers=h, params={"semester_id": sc["sem_id"], "week_no": 1})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert all(int(it["task_id"]) != sc["task_w1"] for it in data["items"])
    assert data["total"] == 0


def test_overdue_unexecuted_counted(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    # 无提交 + 回拨截止已过 + 结算 → OVERDUE_UNEXECUTED；当前亦未完成
    day = _deadline_day(session, sc["sem_id"], _MON1_D)
    day.deadline_at = utcnow() - timedelta(hours=1)
    session.commit()
    _post(client, h, _SETTLE, {"semester_id": sc["sem_id"], "inspection_date": _MON1})
    resp = client.get(_STATS_INC, headers=h, params={"semester_id": sc["sem_id"], "week_no": 1})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["overdue_unexecuted_count"] == 1
    assert data["current_incomplete_count"] == 1
    item = data["items"][0]
    assert item["current_incomplete"] is True
    assert item["deadline_assessment"] == "OVERDUE_UNEXECUTED"


# --------------------------------------------------------------------------- #
# 查询校验：窗口互斥 / 必选其一 → 422
# --------------------------------------------------------------------------- #
def test_window_conflict_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    r = client.get(
        _STATS_ATT,
        headers=h,
        params={
            "semester_id": sc["sem_id"],
            "week_no": 1,
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        },
    )
    assert r.status_code == 422, r.text


def test_window_missing_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene2(client, h, session)
    r = client.get(_STATS_ATT, headers=h, params={"semester_id": sc["sem_id"]})
    assert r.status_code == 422, r.text
