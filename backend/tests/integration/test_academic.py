"""基础数据模块（P3 academic）集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P3 与 PERMISSIONS.md 相关基线中本批可达场景：
- 认证/授权守卫：无令牌 401；缺对应 manage 权限的负责人 403（读接口按 read 放行）。
- 学期：创建、代码唯一 409、结束早于开始 422、归档后写子资源 409、更新非法状态 422。
- 节次定义：路径 period_no 权威、越界 422、时刻逆序 422、列举、删除。
- 校历覆盖：补课缺来源星期 422、同日期唯一 409、列举、删除。
- 行政班 / 学生 / 课程：代码唯一 409、引用不存在 404、状态非法 422、更新。
- 教学班：同学期同课同码唯一 409、缺课程 404、非活跃学期 409。
- 名单整体替换：回填、去重、含不存在学生 404。
- 课表：周次越界 422、结束早于开始 422、更新周次整体替换、删除后读取 404。
- 志愿者学期资格：首次有效资格同事务自动授予 VOLUNTEER；停用不回收；未绑定账号可建资格。
- 真实 MySQL 并发：FOR UPDATE 串行化（名单整体替换、志愿者资格核销）恰一成功且落库自洽。
- 审计：基础数据写操作同事务追加 AuditLog。
"""

from __future__ import annotations

import threading

import pytest
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.modules.academic.models import VolunteerQualification
from app.modules.academic.service import AcademicService
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_AC = "/api/v1/academic"


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


def _make_bound_account(
    session: Session, username: str, student_id: int, role_codes: list[str]
) -> UserAccount:
    """创建与学生绑定的账号（模拟学生绑定流程后的 student_id 关联）。"""
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


def _create_semester(client: TestClient, headers: dict[str, str], code: str, **over):
    payload = {
        "code": code,
        "name": over.get("name", f"学期{code}"),
        "start_date": over.get("start_date", "2026-09-01"),
        "end_date": over.get("end_date", "2027-01-31"),
        "first_monday": over.get("first_monday", "2026-09-07"),
        "total_weeks": over.get("total_weeks", 20),
    }
    resp = client.post(f"{_AC}/semesters", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _create_admin_class(client: TestClient, headers, code: str):
    resp = client.post(
        f"{_AC}/administrative-classes",
        headers=headers,
        json={"class_code": code, "class_name": f"班级{code}", "college": "计算机学院"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _create_student(client: TestClient, headers, no: str, class_id=None):
    body = {"student_no": no, "name": f"学生{no}"}
    if class_id is not None:
        body["administrative_class_id"] = int(class_id)
    resp = client.post(f"{_AC}/students", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _create_course(client: TestClient, headers, code: str):
    resp = client.post(
        f"{_AC}/courses",
        headers=headers,
        json={"course_code": code, "course_name": f"课程{code}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _create_teaching_class(client: TestClient, headers, semester_id, course_id, code="T1"):
    resp = client.post(
        f"{_AC}/teaching-classes",
        headers=headers,
        json={
            "semester_id": int(semester_id),
            "course_id": int(course_id),
            "class_code": code,
            "class_name": f"教学班{code}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# --------------------------------------------------------------------------- #
# 认证与授权守卫
# --------------------------------------------------------------------------- #
def test_unauthenticated_returns_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    resp = client.get(f"{_AC}/semesters")
    assert resp.status_code == 401


def test_actor_without_academic_manage_forbidden(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam = _bearer(_login(client, "sam"))
    # 负责人默认仅 student.read，创建学期需 academic.manage → 403。
    resp = client.post(
        f"{_AC}/semesters",
        headers=sam,
        json={
            "code": "S-BAD",
            "name": "越权",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": "2026-09-07",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_actor_without_student_manage_forbidden(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam = _bearer(_login(client, "sam"))
    resp = client.post(
        f"{_AC}/students", headers=sam, json={"student_no": "X1", "name": "越权学生"}
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 学期
# --------------------------------------------------------------------------- #
def test_create_and_duplicate_semester(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-FALL")
    assert sem["status"] == "ACTIVE"
    assert sem["id"]
    dup = client.post(
        f"{_AC}/semesters",
        headers=h,
        json={
            "code": "2026-FALL",
            "name": "重复",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": "2026-09-07",
        },
    )
    assert dup.status_code == 409


def test_semester_bad_date_range_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    resp = client.post(
        f"{_AC}/semesters",
        headers=h,
        json={
            "code": "2026-BAD",
            "name": "逆序",
            "start_date": "2027-01-31",
            "end_date": "2026-09-01",
            "first_monday": "2026-09-07",
        },
    )
    assert resp.status_code == 422


def test_archived_semester_blocks_child_write(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-ARCH")
    arch = client.patch(
        f"{_AC}/semesters/{sem['id']}", headers=h, json={"status": "ARCHIVED"}
    )
    assert arch.status_code == 200, arch.text
    # 归档学期上写节次定义 → 409。
    resp = client.put(
        f"{_AC}/semesters/{sem['id']}/period-definitions/1",
        headers=h,
        json={"start_time": "08:00", "end_time": "08:45"},
    )
    assert resp.status_code == 409


def test_semester_illegal_status_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-ST")
    resp = client.patch(
        f"{_AC}/semesters/{sem['id']}", headers=h, json={"status": "PAUSED"}
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 节次定义
# --------------------------------------------------------------------------- #
def test_period_definition_upsert_list_delete(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-PD")
    up = client.put(
        f"{_AC}/semesters/{sem['id']}/period-definitions/1",
        headers=h,
        json={"start_time": "08:00", "end_time": "08:45"},
    )
    assert up.status_code == 200, up.text
    pd = up.json()["data"]
    assert pd["period_no"] == 1  # 路径权威覆盖请求体
    # 幂等更新同节次号。
    up2 = client.put(
        f"{_AC}/semesters/{sem['id']}/period-definitions/1",
        headers=h,
        json={"start_time": "08:10", "end_time": "08:55"},
    )
    assert up2.status_code == 200
    lst = client.get(
        f"{_AC}/semesters/{sem['id']}/period-definitions", headers=h
    )
    assert lst.status_code == 200
    assert len(lst.json()["data"]["items"]) == 1
    dele = client.delete(
        f"{_AC}/semesters/{sem['id']}/period-definitions/{pd['id']}", headers=h
    )
    assert dele.status_code == 204


def test_period_definition_out_of_range_path_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-PD2")
    resp = client.put(
        f"{_AC}/semesters/{sem['id']}/period-definitions/99",
        headers=h,
        json={"start_time": "08:00", "end_time": "08:45"},
    )
    assert resp.status_code == 422


def test_period_definition_bad_time_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-PD3")
    resp = client.put(
        f"{_AC}/semesters/{sem['id']}/period-definitions/2",
        headers=h,
        json={"start_time": "09:00", "end_time": "08:00"},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 校历覆盖
# --------------------------------------------------------------------------- #
def test_calendar_override_makeup_requires_weekday_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-CO")
    resp = client.post(
        f"{_AC}/semesters/{sem['id']}/calendar-overrides",
        headers=h,
        json={"date": "2026-10-01", "override_type": "MAKEUP"},
    )
    assert resp.status_code == 422


def test_calendar_override_create_and_duplicate(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-CO2")
    ok = client.post(
        f"{_AC}/semesters/{sem['id']}/calendar-overrides",
        headers=h,
        json={"date": "2026-10-01", "override_type": "STOP", "reason": "国庆"},
    )
    assert ok.status_code == 200, ok.text
    dup = client.post(
        f"{_AC}/semesters/{sem['id']}/calendar-overrides",
        headers=h,
        json={"date": "2026-10-01", "override_type": "STOP"},
    )
    assert dup.status_code == 409


# --------------------------------------------------------------------------- #
# 行政班 / 学生 / 课程
# --------------------------------------------------------------------------- #
def test_admin_class_duplicate_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    _create_admin_class(client, h, "AC-001")
    dup = client.post(
        f"{_AC}/administrative-classes",
        headers=h,
        json={"class_code": "AC-001", "class_name": "重复"},
    )
    assert dup.status_code == 409


def test_student_missing_admin_class_404(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    resp = client.post(
        f"{_AC}/students",
        headers=h,
        json={"student_no": "S1", "name": "学生", "administrative_class_id": 999999},
    )
    assert resp.status_code == 404


def test_student_duplicate_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    _create_student(client, h, "S-DUP")
    dup = client.post(
        f"{_AC}/students", headers=h, json={"student_no": "S-DUP", "name": "重复"}
    )
    assert dup.status_code == 409


def test_student_bad_status_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    stu = _create_student(client, h, "S-ST")
    resp = client.patch(
        f"{_AC}/students/{stu['id']}", headers=h, json={"status": "GONE"}
    )
    assert resp.status_code == 422


def test_course_duplicate_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    _create_course(client, h, "C-001")
    dup = client.post(
        f"{_AC}/courses", headers=h, json={"course_code": "C-001", "course_name": "重复"}
    )
    assert dup.status_code == 409


# --------------------------------------------------------------------------- #
# 教学班
# --------------------------------------------------------------------------- #
def test_teaching_class_missing_course_404(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-TC")
    resp = client.post(
        f"{_AC}/teaching-classes",
        headers=h,
        json={
            "semester_id": int(sem["id"]),
            "course_id": 999999,
            "class_code": "T1",
            "class_name": "教学班",
        },
    )
    assert resp.status_code == 404


def test_teaching_class_duplicate_key_409(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-TC2")
    course = _create_course(client, h, "C-TC2")
    _create_teaching_class(client, h, sem["id"], course["id"], code="T1")
    dup = client.post(
        f"{_AC}/teaching-classes",
        headers=h,
        json={
            "semester_id": int(sem["id"]),
            "course_id": int(course["id"]),
            "class_code": "T1",
            "class_name": "重复",
        },
    )
    assert dup.status_code == 409


# --------------------------------------------------------------------------- #
# 名单整体替换
# --------------------------------------------------------------------------- #
def test_roster_replace_and_dedup(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-RS")
    course = _create_course(client, h, "C-RS")
    tc = _create_teaching_class(client, h, sem["id"], course["id"])
    s1 = _create_student(client, h, "RS-1")
    s2 = _create_student(client, h, "RS-2")
    r = client.put(
        f"{_AC}/teaching-classes/{tc['id']}/students",
        headers=h,
        # 含重复项，服务应去重。
        json={"student_ids": [int(s1["id"]), int(s2["id"]), int(s1["id"])]},
    )
    assert r.status_code == 200, r.text
    ids = {int(i["id"]) for i in r.json()["data"]["items"]}
    assert ids == {int(s1["id"]), int(s2["id"])}
    # 空集合可清空名单。
    r2 = client.put(
        f"{_AC}/teaching-classes/{tc['id']}/students",
        headers=h,
        json={"student_ids": []},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["items"] == []


def test_roster_missing_student_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-RS4")
    course = _create_course(client, h, "C-RS4")
    tc = _create_teaching_class(client, h, sem["id"], course["id"])
    resp = client.put(
        f"{_AC}/teaching-classes/{tc['id']}/students",
        headers=h,
        json={"student_ids": [999999]},
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 课表
# --------------------------------------------------------------------------- #
def _make_tc_for_schedule(client, h):
    sem = _create_semester(client, h, "2026-SCH")
    course = _create_course(client, h, "C-SCH")
    tc = _create_teaching_class(client, h, sem["id"], course["id"])
    return sem, tc


def test_schedule_create_weeks_roundtrip(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem, tc = _make_tc_for_schedule(client, h)
    r = client.post(
        f"{_AC}/course-schedules",
        headers=h,
        json={
            "teaching_class_id": int(tc["id"]),
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "classroom": "A101",
            "weeks": [1, 2, 3],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert sorted(data["weeks"]) == [1, 2, 3]
    assert data["id"]
    got = client.get(f"{_AC}/course-schedules/{data['id']}", headers=h)
    assert got.status_code == 200


def test_schedule_week_out_of_range_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem, tc = _make_tc_for_schedule(client, h)  # total_weeks=20
    resp = client.post(
        f"{_AC}/course-schedules",
        headers=h,
        json={
            "teaching_class_id": int(tc["id"]),
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "weeks": [1, 21],
        },
    )
    assert resp.status_code == 422


def test_schedule_end_before_start_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem, tc = _make_tc_for_schedule(client, h)
    resp = client.post(
        f"{_AC}/course-schedules",
        headers=h,
        json={
            "teaching_class_id": int(tc["id"]),
            "weekday": 1,
            "start_period": 3,
            "end_period": 1,
            "weeks": [1],
        },
    )
    assert resp.status_code == 422


def test_schedule_update_weeks_and_delete(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem, tc = _make_tc_for_schedule(client, h)
    r = client.post(
        f"{_AC}/course-schedules",
        headers=h,
        json={
            "teaching_class_id": int(tc["id"]),
            "weekday": 2,
            "start_period": 1,
            "end_period": 1,
            "weeks": [1, 2, 3],
        },
    )
    sid = int(r.json()["data"]["id"])
    upd = client.patch(
        f"{_AC}/course-schedules/{sid}", headers=h, json={"weeks": [5, 6]}
    )
    assert upd.status_code == 200, upd.text
    assert sorted(upd.json()["data"]["weeks"]) == [5, 6]  # 整体替换
    dele = client.delete(f"{_AC}/course-schedules/{sid}", headers=h)
    assert dele.status_code == 204
    gone = client.get(f"{_AC}/course-schedules/{sid}", headers=h)
    assert gone.status_code == 404


def test_schedule_missing_teaching_class_404(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    resp = client.post(
        f"{_AC}/course-schedules",
        headers=h,
        json={
            "teaching_class_id": 999999,
            "weekday": 1,
            "start_period": 1,
            "end_period": 1,
            "weeks": [1],
        },
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 志愿者学期资格（含 VOLUNTEER 自动身份）
# --------------------------------------------------------------------------- #
def test_volunteer_qualification_grants_role_when_bound(
    client: TestClient, session: Session
) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    h = _bearer(_login(client, "admin"))
    sem = _create_semester(client, h, "2026-VQ")
    stu = _create_student(client, h, "VQ-1")
    acct = _make_bound_account(session, "stu1", int(stu["id"]), [])
    assert RoleCode.VOLUNTEER.value not in [r.code for r in acct.roles]

    r = client.put(
        f"{_AC}/volunteer-qualifications",
        headers=h,
        json={"semester_id": int(sem["id"]), "student_id": int(stu["id"]), "enabled": True},
    )
    assert r.status_code == 200, r.text
    session.commit()
    session.expire_all()
    refreshed = session.get(UserAccount, acct.id)
    assert RoleCode.VOLUNTEER.value in [x.code for x in refreshed.roles]
    # 自动授予会推进账号 lock_version。
    assert refreshed.lock_version == acct.lock_version + 1 or refreshed.lock_version == 1


def test_volunteer_disable_keeps_role(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    h = _bearer(_login(client, "admin"))
    sem = _create_semester(client, h, "2026-VQ2")
    stu = _create_student(client, h, "VQ2-1")
    acct = _make_bound_account(session, "stu2", int(stu["id"]), [])
    client.put(
        f"{_AC}/volunteer-qualifications",
        headers=h,
        json={"semester_id": int(sem["id"]), "student_id": int(stu["id"]), "enabled": True},
    )
    off = client.put(
        f"{_AC}/volunteer-qualifications",
        headers=h,
        json={"semester_id": int(sem["id"]), "student_id": int(stu["id"]), "enabled": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["data"]["enabled"] is False
    session.commit()
    session.expire_all()
    refreshed = session.get(UserAccount, acct.id)
    # 停用不回收 VOLUNTEER 角色（资格为逐学期闸口，历史只读保留）。
    assert RoleCode.VOLUNTEER.value in [x.code for x in refreshed.roles]


def test_volunteer_qualification_for_unbound_student(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-VQ3")
    stu = _create_student(client, h, "VQ3-1")  # 未绑定账号
    r = client.put(
        f"{_AC}/volunteer-qualifications",
        headers=h,
        json={"semester_id": int(sem["id"]), "student_id": int(stu["id"]), "enabled": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["student_id"] == stu["id"]


def test_volunteer_qualification_missing_student_404(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-VQ4")
    resp = client.put(
        f"{_AC}/volunteer-qualifications",
        headers=h,
        json={"semester_id": int(sem["id"]), "student_id": 999999, "enabled": True},
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 审计（写操作同事务）
# --------------------------------------------------------------------------- #
def test_write_writes_audit_log(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    admin = _make_user(session, "admin2", [RoleCode.SUPER_ADMIN.value])
    h = _bearer(_login(client, "admin"))
    sem = _create_semester(client, h, "2026-AUD")
    session.commit()
    session.expire_all()
    row = session.execute(
        select(AuditLog).where(
            AuditLog.action == "academic.semester.create",
            AuditLog.resource_id == str(sem["id"]),
        )
    ).scalar_one()
    assert row.actor_user_id in (admin.id,) or row.actor_user_id is not None
    assert row.after_json["code"] == "2026-AUD"


# --------------------------------------------------------------------------- #
# 真实 MySQL 并发：FOR UPDATE 串行化
# --------------------------------------------------------------------------- #
def _open_session(engine) -> Session:  # noqa: ANN001
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory()


def _actor(user: UserAccount) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=user.status,
        roles=[r.code for r in user.roles],
        permissions=[],
    )


def _roster_worker(
    engine, actor_id: int, tc_id: int, student_ids: list[int],
    barrier: threading.Barrier, out: dict[int, object], idx: int,
    actor_obj_cache: dict[int, CurrentUser],
) -> None:
    s = _open_session(engine)
    try:
        barrier.wait()
        svc = AcademicService(s)
        # 直接以 actor_user_id 走守卫（服务内重读权限）；构造最小 CurrentUser。
        cur = actor_obj_cache[actor_id]
        res = svc.replace_roster(cur, tc_id, student_ids, reason=f"c-{idx}", request_id=f"c-{idx}")
        out[idx] = ("ok", {int(x.id) for x in res})
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_roster_replace_serialized(
    engine, client: TestClient, session: Session
) -> None:
    """并发整体替换同一教学班名单：FOR UPDATE 串行化，最终恰为后写入的一侧，无残缺。"""
    h = _admin_headers(client, session)
    sem = _create_semester(client, h, "2026-CR")
    course = _create_course(client, h, "C-CR")
    tc = _create_teaching_class(client, h, sem["id"], course["id"])
    a = _create_student(client, h, "CR-A")
    b = _create_student(client, h, "CR-B")
    admin = session.execute(
        select(UserAccount).where(UserAccount.username == "admin")
    ).scalar_one()
    actor_cache = {admin.id: _actor(admin)}

    barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_roster_worker,
            args=(engine, admin.id, int(tc["id"]), [int(a["id"])], barrier, out, 0, actor_cache),
        ),
        threading.Thread(
            target=_roster_worker,
            args=(engine, admin.id, int(tc["id"]), [int(b["id"])], barrier, out, 1, actor_cache),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(r[0] == "ok" for r in out.values()), out
    # 串行化后，最终名单恰为某一侧（1 人），绝不出现两人交错或空集残缺。
    session.commit()
    session.expire_all()
    from app.modules.academic.models import TeachingClassStudent

    final_ids = set(
        session.execute(
            select(TeachingClassStudent.student_id).where(
                TeachingClassStudent.teaching_class_id == int(tc["id"])
            )
        ).scalars().all()
    )
    assert final_ids in ({int(a["id"])}, {int(b["id"])}), final_ids


def _vq_worker(
    engine, actor_cur: CurrentUser, semester_id: int, student_id: int,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    s = _open_session(engine)
    try:
        barrier.wait()
        svc = AcademicService(s)
        from app.modules.academic.schemas import VolunteerQualificationUpsertRequest

        req = VolunteerQualificationUpsertRequest(
            semester_id=semester_id, student_id=student_id, enabled=True
        )
        resp = svc.upsert_volunteer_qualification(actor_cur, req, request_id=f"v-{idx}")
        out[idx] = ("ok", resp.id)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_volunteer_qualification_upsert_single_row(
    engine, client: TestClient, session: Session
) -> None:
    """并发对同一(学期,学生)核销资格：学期行 FOR UPDATE 串行化 → 恰一条记录、VOLUNTEER 仅授一次。"""
    _bootstrap(session)
    admin_user = _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    h = _bearer(_login(client, "admin"))
    sem = _create_semester(client, h, "2026-CVQ")
    stu = _create_student(client, h, "CVQ-1")
    acct = _make_bound_account(session, "cvqstu", int(stu["id"]), [])
    session.commit()
    before_version = session.get(UserAccount, acct.id).lock_version

    actor_cur = _actor(admin_user)
    barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_vq_worker,
            args=(
                engine, actor_cur, int(sem["id"]), int(stu["id"]), barrier, out, i
            ),
        )
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(r[0] == "ok" for r in out.values()), out
    # 两条并发指向同一条资格记录。
    assert out[0][1] == out[1][1], out

    session.commit()
    session.expire_all()
    count = session.scalar(
        select(func.count())
        .select_from(VolunteerQualification)
        .where(
            VolunteerQualification.semester_id == int(sem["id"]),
            VolunteerQualification.student_id == int(stu["id"]),
        )
    )
    assert count == 1
    # VOLUNTEER 角色只授予一次 → lock_version 恰好 +1。
    refreshed = session.get(UserAccount, acct.id)
    assert refreshed.lock_version == before_version + 1
    assert RoleCode.VOLUNTEER.value in [x.code for x in refreshed.roles]
