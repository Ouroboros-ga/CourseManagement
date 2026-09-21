"""查课任务生成（P4 Wave 2：预览→生成两步、task_key 幂等、名单快照冻结、
首次建当日截止记录、有界规模、整批单事务原子）集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P4 与 PERMISSIONS.md 4.3/7/12.6：
- 认证 / 功能守卫：无令牌 401；有 inspection.read 缺 inspection.generate → 预览/生成 403。
- 预览只读：返回计划口径（task_count/new/existing/date_count/student_total），且零写库。
- COURSE 生成：建任务 + 名单版本 v1 + 成员快照 + 当日截止记录 v1（默认 22:00 本地转 UTC-naive）
  + 审计 inspection.task.generate 一条；课程/班级/教室快照冻结。
- 幂等：重复生成命中既有 task_key → created=0、existed>0、deadline 不再补种。
- 名单快照：成员 student_no/name/class_name/grade_year 随版本冻结。
- MORNING_STUDY：按行政班 + 显式节次，逐日建任务，人数取行政班在册 ACTIVE 学生。
- 校历 STOP：停办日跳过，不生成任务。
- 规模上限：INSPECTION_GENERATE_MAX_TASKS 越小可触发 422（预览与生成同口径）。
- 参数校验：周次越界 422；教学班不属于该学期 422；教学班不存在 404；归档学期生成 409。
- 读取范围：列表/详情走 inspection.read；/me 仅本人受派（Wave 2 无受派故空）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.inspection.models import (
    InspectionTask,
    SubmissionDeadlineDay,
    SubmissionDeadlineVersion,
    TaskRosterMember,
    TaskRosterVersion,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_PREV = "/api/v1/inspection-tasks/preview"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"

# 学期基准：首周一 2026-09-07（第 1 周周一），共 20 周。
_FIRST_MONDAY = date(2026, 9, 7)


# --------------------------------------------------------------------------- #
# 装配助手
# --------------------------------------------------------------------------- #
def _bootstrap(session: Session) -> None:
    sync_registry(session)
    session.commit()


def _role(session: Session, code: str) -> Role:
    return session.execute(select(Role).where(Role.code == code)).scalar_one()


def _make_user(session: Session, username: str, role_codes: list[str]) -> UserAccount:
    user = UserAccount(
        username=username,
        password_hash=hash_password(_PWD),
        display_name=username,
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [_role(session, c) for c in role_codes]
    session.add(user)
    session.commit()
    return user


def _make_perm_user(session: Session, username: str, perm_codes: list[str]) -> UserAccount:
    """挂载一个仅含指定权限码的自定义角色，用于精确构造功能守卫象限。"""
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
    return client.post(url, headers=headers, json=body)


def _scene(client: TestClient, headers: dict[str, str]) -> dict:
    """建 ACTIVE 学期 + 行政班 + 两名在册学生 + 课程 + 教学班 + 周一 1-2 节课表 + 名单。

    第 1 周周一为 2026-09-07，与课表 weekday=1、weeks 覆盖第 1 周对齐，
    故 COURSE week_nos=[1] 恰好命中 1 个任务。
    """
    sem = _post(
        client,
        headers,
        f"{_ACA}/semesters",
        {
            "code": "2026FA",
            "name": "2026秋",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": "2026-09-07",
            "total_weeks": 20,
        },
    ).json()["data"]
    cls = _post(
        client,
        headers,
        f"{_ACA}/administrative-classes",
        {
            "class_code": "CS2401",
            "class_name": "计算机2401",
            "college": "计算机学院",
            "grade_year": 2024,
        },
    ).json()["data"]
    students = {}
    for no in ("S001", "S002"):
        students[no] = _post(
            client,
            headers,
            f"{_ACA}/students",
            {
                "student_no": no,
                "name": f"学生{no}",
                "administrative_class_id": int(cls["id"]),
            },
        ).json()["data"]
    course = _post(
        client,
        headers,
        f"{_ACA}/courses",
        {"course_code": "C001", "course_name": "高等数学"},
    ).json()["data"]
    tc = _post(
        client,
        headers,
        f"{_ACA}/teaching-classes",
        {
            "semester_id": int(sem["id"]),
            "course_id": int(course["id"]),
            "class_code": "T1",
            "class_name": "教学班T1",
        },
    ).json()["data"]
    # 教学班名单：放入两名学生。
    rp = client.put(
        f"{_ACA}/teaching-classes/{int(tc['id'])}/students",
        headers=headers,
        json={"student_ids": [int(students["S001"]["id"]), int(students["S002"]["id"])]},
    )
    assert rp.status_code == 200, rp.text
    sched = _post(
        client,
        headers,
        f"{_ACA}/course-schedules",
        {
            "teaching_class_id": int(tc["id"]),
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "classroom": "A101",
            "weeks": [1, 2, 3, 4, 5],
        },
    ).json()["data"]
    return {
        "semester_id": int(sem["id"]),
        "class_id": int(cls["id"]),
        "students": students,
        "course_id": int(course["id"]),
        "tc_id": int(tc["id"]),
        "schedule_id": int(sched["id"]),
    }


def _count(session: Session, model) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def _defer_deadline(session: Session, sem_id: int, on_date: date) -> None:
    """把某查课日截止推到未来：演示查课日 2026-09-07 的默认 22:00 截止早于系统今天，
    五态精判会得“已逾期”；需验“待执行”的用例先把截止推后（与 Wave 3c 同处理）。"""
    day = session.execute(
        select(SubmissionDeadlineDay).where(
            SubmissionDeadlineDay.semester_id == sem_id,
            SubmissionDeadlineDay.inspection_date == on_date,
        )
    ).scalar_one()
    day.deadline_at = utcnow() + timedelta(hours=48)
    session.commit()


def _audit_actions(session: Session, action: str) -> int:
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


# --------------------------------------------------------------------------- #
# 认证与功能守卫
# --------------------------------------------------------------------------- #
def test_generate_requires_auth_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    assert client.post(_PREV, json={}).status_code == 401
    assert client.post(_GEN, json={}).status_code == 401


def test_read_only_user_cannot_generate_403(
    client: TestClient, session: Session
) -> None:
    # 持 inspection.read 但缺 inspection.generate → 预览 / 生成路由早拦 403。
    _bootstrap(session)
    _make_perm_user(
        session, "reader", [PermissionCode.INSPECTION_READ.value]
    )
    h = _bearer(_login(client, "reader"))
    body = {
        "semester_id": 1,
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [1],
    }
    assert client.post(_PREV, headers=h, json=body).status_code == 403
    assert client.post(_GEN, headers=h, json=body).status_code == 403


# --------------------------------------------------------------------------- #
# 预览：只读零写库
# --------------------------------------------------------------------------- #
def test_preview_is_read_only(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    resp = client.post(_PREV, headers=h, json=body)
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["task_count"] == 1
    assert d["new_task_count"] == 1
    assert d["existing_task_count"] == 0
    assert d["date_count"] == 1
    assert d["student_total"] == 2
    assert d["within_limit"] is True
    assert d["sample"][0]["course_name_snapshot"] == "高等数学"
    assert d["sample"][0]["classroom_snapshot"] == "A101"

    # 预览绝不写库。
    session.expire_all()
    assert _count(session, InspectionTask) == 0
    assert _count(session, SubmissionDeadlineDay) == 0


# --------------------------------------------------------------------------- #
# COURSE 生成：任务 + 名单快照 + 截止记录 + 审计
# --------------------------------------------------------------------------- #
def test_course_generate_full_wave2(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
        "require_photo": True,
        "reason": "开学第一周查课",
    }
    resp = client.post(_GEN, headers=h, json=body)
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["created"] == 1
    assert d["existed"] == 0
    assert d["total_planned"] == 1
    assert d["deadline_days_seeded"] == 1

    session.expire_all()
    task = session.execute(select(InspectionTask)).scalar_one()
    assert task.inspection_type == "COURSE"
    assert task.inspection_date == date(2026, 9, 7)
    assert task.week_no == 1
    assert task.start_period == 1
    assert task.end_period == 2
    assert task.course_schedule_id == sc["schedule_id"]
    assert task.teaching_class_id == sc["tc_id"]
    assert task.course_name_snapshot == "高等数学"
    assert task.class_name_snapshot == "教学班T1"
    assert task.classroom_snapshot == "A101"
    assert task.require_photo_snapshot is True
    assert task.roster_version == 1
    assert task.expected_count_snapshot == 2
    assert task.expected_count_current == 2
    assert task.lock_version == 0

    # 名单版本 v1 + 成员快照。
    rv = session.execute(
        select(TaskRosterVersion).where(TaskRosterVersion.task_id == task.id)
    ).scalars().all()
    assert len(rv) == 1
    assert rv[0].version_no == 1
    members = session.execute(
        select(TaskRosterMember).where(TaskRosterMember.task_id == task.id)
    ).scalars().all()
    assert {m.student_no for m in members} == {"S001", "S002"}
    assert all(m.class_name_snapshot == "计算机2401" for m in members)
    assert all(m.grade_year_snapshot == 2024 for m in members)

    # 当日截止记录 v1：本地 22:00 − 8h 偏移 = 当日 14:00（naive-UTC）。
    day = session.execute(select(SubmissionDeadlineDay)).scalar_one()
    assert day.inspection_date == date(2026, 9, 7)
    assert day.version == 1
    assert day.deadline_at == datetime(2026, 9, 7, 14, 0, 0)
    ver = session.execute(
        select(SubmissionDeadlineVersion).where(
            SubmissionDeadlineVersion.deadline_day_id == day.id
        )
    ).scalars().all()
    assert len(ver) == 1
    assert ver[0].version_no == 1
    assert ver[0].deadline_at == day.deadline_at

    # 审计一条。
    assert _audit_actions(session, "inspection.task.generate") == 1


# --------------------------------------------------------------------------- #
# 幂等：重复生成跳过既有
# --------------------------------------------------------------------------- #
def test_generate_idempotent_skip(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    first = client.post(_GEN, headers=h, json=body).json()["data"]
    assert first["created"] == 1
    second = client.post(_GEN, headers=h, json=body)
    assert second.status_code == 200, second.text
    d = second.json()["data"]
    assert d["created"] == 0
    assert d["existed"] == 1
    assert d["total_planned"] == 1
    assert d["deadline_days_seeded"] == 0

    session.expire_all()
    assert _count(session, InspectionTask) == 1
    assert _count(session, SubmissionDeadlineDay) == 1


# --------------------------------------------------------------------------- #
# MORNING_STUDY：行政班逐日建任务
# --------------------------------------------------------------------------- #
def test_study_generate_per_day(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "MORNING_STUDY",
        "date_from": "2026-09-07",
        "date_to": "2026-09-08",
        "administrative_class_ids": [sc["class_id"]],
        "start_period": 1,
        "end_period": 1,
    }
    resp = client.post(_GEN, headers=h, json=body)
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    assert d["created"] == 2  # 两天各一个任务
    assert d["deadline_days_seeded"] == 2

    session.expire_all()
    tasks = session.execute(
        select(InspectionTask).where(
            InspectionTask.inspection_type == "MORNING_STUDY"
        )
    ).scalars().all()
    assert {t.inspection_date for t in tasks} == {date(2026, 9, 7), date(2026, 9, 8)}
    assert all(t.administrative_class_id == sc["class_id"] for t in tasks)
    assert all(t.expected_count_snapshot == 2 for t in tasks)
    assert all(t.course_schedule_id is None for t in tasks)


# --------------------------------------------------------------------------- #
# 校历 STOP：停办日跳过
# --------------------------------------------------------------------------- #
def test_calendar_stop_skips_task(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 把第 1 周周一（原定有课）标为停办。
    ov = client.post(
        f"{_ACA}/semesters/{sc['semester_id']}/calendar-overrides",
        headers=h,
        json={"date": "2026-09-07", "override_type": "STOP", "reason": "放假"},
    )
    assert ov.status_code == 200, ov.text

    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    prev = client.post(_PREV, headers=h, json=body).json()["data"]
    assert prev["task_count"] == 0
    gen = client.post(_GEN, headers=h, json=body).json()["data"]
    assert gen["created"] == 0
    session.expire_all()
    assert _count(session, InspectionTask) == 0


# --------------------------------------------------------------------------- #
# 规模上限：预览与生成同口径 422
# --------------------------------------------------------------------------- #
def test_scale_limit_422(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "MORNING_STUDY",
        "date_from": "2026-09-07",
        "date_to": "2026-09-09",  # 3 天 → 计划 3 个任务
        "administrative_class_ids": [sc["class_id"]],
        "start_period": 1,
        "end_period": 1,
    }
    monkeypatch.setenv("INSPECTION_GENERATE_MAX_TASKS", "2")
    get_settings.cache_clear()
    try:
        prev = client.post(_PREV, headers=h, json=body)
        assert prev.status_code == 422
        gen = client.post(_GEN, headers=h, json=body)
        assert gen.status_code == 422
        session.expire_all()
        assert _count(session, InspectionTask) == 0
    finally:
        monkeypatch.delenv("INSPECTION_GENERATE_MAX_TASKS", raising=False)
        get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# 参数与状态校验
# --------------------------------------------------------------------------- #
def test_week_out_of_range_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [99],
        "teaching_class_ids": [sc["tc_id"]],
    }
    assert client.post(_PREV, headers=h, json=body).status_code == 422


def test_selection_missing_both_date_and_week_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "teaching_class_ids": [sc["tc_id"]],
    }
    assert client.post(_PREV, headers=h, json=body).status_code == 422


def test_teaching_class_wrong_semester_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 造第二个学期（ACTIVE），但教学班仍属第一个学期 → 422。
    sem2 = _post(
        client,
        h,
        f"{_ACA}/semesters",
        {
            "code": "2027SP",
            "name": "2027春",
            "start_date": "2027-02-01",
            "end_date": "2027-07-31",
            "first_monday": "2027-03-01",
            "total_weeks": 18,
        },
    ).json()["data"]
    body = {
        "semester_id": int(sem2["id"]),
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    assert client.post(_PREV, headers=h, json=body).status_code == 422


def test_teaching_class_not_found_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [999999],
    }
    assert client.post(_PREV, headers=h, json=body).status_code == 404


def test_generate_on_archived_semester_409(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    arch = client.patch(
        f"{_ACA}/semesters/{sc['semester_id']}", headers=h, json={"status": "ARCHIVED"}
    )
    assert arch.status_code == 200, arch.text
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    assert client.post(_GEN, headers=h, json=body).status_code == 409


# --------------------------------------------------------------------------- #
# 读取：列表 / 详情 / 本人任务范围
# --------------------------------------------------------------------------- #
def test_list_and_get_task(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    client.post(_GEN, headers=h, json=body)
    # 演示查课日已早于今天，先把当日截止推后，才能断言“待执行”（否则精判为“已逾期”）。
    _defer_deadline(session, sc["semester_id"], date(2026, 9, 7))

    lst = client.get(_TASKS, headers=h, params={"semester_id": sc["semester_id"]})
    assert lst.status_code == 200, lst.text
    items = lst.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "待执行"
    assert items[0]["assignment"] is None
    task_id = int(items[0]["id"])

    detail = client.get(f"{_TASKS}/{task_id}", headers=h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["task_key"] == items[0]["task_key"]

    roster = client.get(f"{_TASKS}/{task_id}/students", headers=h)
    assert roster.status_code == 200, roster.text
    rd = roster.json()["data"]
    assert rd["roster_version"] == 1
    assert {m["student_no"] for m in rd["items"]} == {"S001", "S002"}


def test_me_tasks_empty_without_assignment(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    client.post(_GEN, headers=h, json=body)
    me = client.get("/api/v1/me/inspection-tasks", headers=h)
    assert me.status_code == 200, me.text
    # 管理员未受派任何任务：/me 强制限定本人受派，故为空。
    assert me.json()["data"]["items"] == []


def test_volunteer_scope_only_assigned(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    body = {
        "semester_id": sc["semester_id"],
        "inspection_type": "COURSE",
        "week_nos": [1],
        "teaching_class_ids": [sc["tc_id"]],
    }
    client.post(_GEN, headers=h, json=body)

    # 志愿者持 inspection.read 但无受派 → 列表范围为空（ASSIGNED_TASK 最小可见）。
    _make_perm_user(session, "vol", [PermissionCode.INSPECTION_READ.value])
    vh = _bearer(_login(client, "vol"))
    lst = client.get(_TASKS, headers=vh)
    assert lst.status_code == 200, lst.text
    assert lst.json()["data"]["items"] == []
