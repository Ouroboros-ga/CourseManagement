"""异议域 P6：创建 / 读取范围 / 初核 / 终审（含改判考勤）/ 并发 / 清理耦合，连真实 MySQL。

覆盖技术方案 14 / 15 / 16.3 与 PERMISSIONS.md 5 / 7.6 / 8：
- 创建守卫与鉴权：无令牌 401；越权（他人考勤 / 不存在）统一 404 防枚举；诉求与当前认定
  相同 → 422；同一考勤已有未完成异议 → 409 DUPLICATE_ACTIVE_OBJECTION；窗口超期 → 409
  OBJECTION_WINDOW_CLOSED；材料非法（不存在 / 未就绪 / 非本人 / 类别不符 / 过期）→ 422。
- 材料关联：合法 OBJECTION_PROOF（本人 / READY / 未过期）落 objection_file，响应回显。
- 读取范围（7.6、8）：本人 OWN 只见自己；管理（教师 / 超管）见全量；负责人默认无读取路径
  → 403，授予可选 objection.initial_review 后派生管理读取（关闭即失去）。
- 初核：PENDING→PASSED/REJECTED，**绝不改考勤**；重复初核 409；无权限 403。
- 终审：驳回不改考勤；通过且需更正 → 同事务改判 + 追加 OBJECTION_FINAL 版本（需
  attendance.correct）；陈旧版本 / 他人新认定 → 409 VERSION_CONFLICT；重复终审 409；
  负责人无终审 → 403。
- 并发：同一考勤双人同时创建，恰好一人成功、另一人 DUPLICATE。
- 清理耦合（16.3）：被未完成异议引用的材料暂停到期清理；异议关闭后重新纳入并清理。
"""

from __future__ import annotations

import threading
from datetime import date as date_
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import ErrorCode
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceRecordVersion,
    AttendanceSourceType,
    AttendanceType,
)
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.service import FileService
from app.modules.file.storage import LocalStorage
from app.modules.identity.models import Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import SubmissionDeadlineDay
from app.modules.objection.models import (
    Objection,
    ObjectionFinalStatus,
    ObjectionInitialStatus,
)
from app.modules.objection.service import ObjectionService
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
# 装配助手（与 test_inspection_review_attendance 同构，令本文件自包含）
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
    resp = client.post(
        "/api/v1/auth/web/login",
        json={"username": username, "password": _PWD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _bearer(data: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {data['access_token']}"}


def _post(client: TestClient, h: dict[str, str], url: str, body: dict) -> dict:
    resp = client.post(url, headers=h, json=body)
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
    d = _post(
        client,
        h,
        f"{_ACA}/courses",
        {"course_code": code, "course_name": f"课程{code}"},
    )
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
    client: TestClient, h: dict[str, str], tc_id: int, start: int, end: int, room: str
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
            "weeks": [1],
        },
    )
    return int(d["id"])


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


def _assign(
    client: TestClient, h: dict[str, str], task_id: int, vol_id: int, version: int = 0
) -> None:
    resp = client.put(
        f"{_TASKS}/{task_id}/assignment",
        headers=h,
        json={"volunteer_user_id": vol_id, "lock_version": version},
    )
    assert resp.status_code == 200, resp.text


def _grant_qual(client: TestClient, h: dict[str, str], sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={"semester_id": sem_id, "student_id": student_id, "enabled": True, "reason": "合格"},
    )
    assert rp.status_code == 200, rp.text


def _scene(client: TestClient, h: dict[str, str]) -> dict:
    """ACTIVE 学期 + 被查班 CS2401(两生 S001/S002) + 教学班 T1，生成 1 任务、1 日截止。"""
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
    _schedule(client, h, t1, 1, 2, "A101")
    assert _gen_course(client, h, sem_id, [t1]) == 1
    tasks = _list_tasks(client, h, sem_id)
    assert len(tasks) == 1
    return {
        "sem_id": sem_id,
        "cs": cs,
        "s1": s1,
        "s2": s2,
        "task_id": int(tasks[0]["id"]),
        "task": tasks[0],
    }


def _make_volunteer(client, h, session, sc, username="vol"):
    other = _create_admin_class(client, h, f"VCLASS_{username}")
    sid = _create_student(client, h, f"V{username}", other)
    _grant_qual(client, h, sc["sem_id"], sid)
    vol = _make_user(session, username, [RoleCode.VOLUNTEER.value], student_id=sid)
    _assign(client, h, sc["task_id"], vol.id)
    return vol, _bearer(_login(client, username))


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


def _normal_body(**over: Any) -> dict:
    body: dict[str, Any] = {"result": "NORMAL", "abnormal_items": [], "file_ids": []}
    body.update(over)
    return body


def _abnormal_body(items: list[dict], **over: Any) -> dict:
    body: dict[str, Any] = {"result": "ABNORMAL", "abnormal_items": items, "file_ids": []}
    body.update(over)
    return body


def _submit_url(task_id: int) -> str:
    return f"{_TASKS}/{task_id}/submissions"


def _review_url(sub_id: int) -> str:
    return f"{_SUBS}/{sub_id}/review"


def _pending_submission(client, h, session, sc, *, abnormal: bool = False) -> int:
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)
    username = f"vol{sc['task_id']}{'abn' if abnormal else ''}"
    _, vh = _make_volunteer(client, h, session, sc, username=username)
    if abnormal:
        items = [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}]
        r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_abnormal_body(items))
    else:
        r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body(note="齐"))
    assert r.status_code == 200, r.text
    return int(r.json()["data"]["id"])


def _approve_setup(client, h, session, sc) -> dict[int, int]:
    """提交 ABNORMAL + 审核通过 → {student_id: attendance_record_id}（s1=LATE、s2=NORMAL）。"""
    sub_id = _pending_submission(client, h, session, sc, abnormal=True)
    assert (
        client.post(_review_url(sub_id), headers=h, json={"decision": "APPROVED"}).status_code
        == 200
    )
    return {r.student_id: r.id for r in _records(session, sc["task_id"])}


def _make_student(session: Session, sc, which: str) -> UserAccount:
    """为 s1 / s2 建 STUDENT 账号并绑定其 student_id（可直接登录取本人令牌）。"""
    sid = sc[which]
    return _make_user(session, f"stu_{which}_{sid}", [RoleCode.STUDENT.value], student_id=sid)


def _student_headers(client: TestClient, session: Session, sc, which: str):
    acct = _make_student(session, sc, which)
    return acct, _bearer(_login(client, f"stu_{which}_{sc[which]}"))


def _relogin(client: TestClient, sc, which: str) -> dict[str, str]:
    """按已建学生账号登录取令牌（不重复建号）。"""
    return _bearer(_login(client, f"stu_{which}_{sc[which]}"))


# --------------------------------------------------------------------------- #
# 事实读助手
# --------------------------------------------------------------------------- #
def _records(session: Session, task_id: int) -> list[AttendanceRecord]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(AttendanceRecord)
            .where(AttendanceRecord.task_id == task_id)
            .order_by(AttendanceRecord.student_id)
        )
        .scalars()
        .all()
    )


def _record(session: Session, record_id: int) -> AttendanceRecord:
    session.commit()
    session.expire_all()
    row = session.get(AttendanceRecord, record_id)
    assert row is not None
    return row


def _versions(session: Session, record_id: int) -> list[AttendanceRecordVersion]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(AttendanceRecordVersion)
            .where(AttendanceRecordVersion.attendance_record_id == record_id)
            .order_by(AttendanceRecordVersion.version_no)
        )
        .scalars()
        .all()
    )


def _objection(session: Session, objection_id: int) -> Objection:
    session.commit()
    session.expire_all()
    row = session.get(Objection, objection_id)
    assert row is not None
    return row


def _audit_count(session: Session, action: str) -> int:
    session.commit()
    session.expire_all()
    from app.modules.audit.models import AuditLog

    return len(session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all())


# --------------------------------------------------------------------------- #
# 异议 HTTP 助手
# --------------------------------------------------------------------------- #
def _create_obj_url(record_id: int) -> str:
    return f"{_ATT}/{record_id}/objections"


def _initial_url(oid: int) -> str:
    return f"{_OBJS}/{oid}/initial-review"


def _final_url(oid: int) -> str:
    return f"{_OBJS}/{oid}/final-review"


def _create_objection(client, sh, record_id, *, desired, reason="情况属实有误", **kw) -> dict:
    body: dict[str, Any] = {"desired_type": desired, "reason": reason}
    body.update(kw)
    resp = client.post(_create_obj_url(record_id), headers=sh, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _open_objection(client, h, session, sc, *, which="s2", desired="LATE") -> tuple[int, int]:
    """建某生账号并对本人考勤提出一条未完成异议 → (objection_id, record_id)。"""
    rec_ids = _approve_setup(client, h, session, sc)
    rec_id = rec_ids[sc[which]]
    _, sh = _student_headers(client, session, sc, which)
    obj = _create_objection(client, sh, rec_id, desired=desired)
    return int(obj["id"]), rec_id


# --------------------------------------------------------------------------- #
# 创建：鉴权 / 归属 / 守卫
# --------------------------------------------------------------------------- #
def test_create_requires_auth_401(client: TestClient) -> None:
    r = client.post(_create_obj_url(1), json={"desired_type": "NORMAL", "reason": "x"})
    assert r.status_code == 401, r.text


def test_create_student_ok_anchors_base_version(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    rid = rec_ids[sc["s2"]]  # NORMAL, current_version 1
    _, sh = _student_headers(client, session, sc, "s2")
    obj = _create_objection(client, sh, rid, desired="LATE", reason="其实迟到了不该记正常")
    assert int(obj["attendance_record_id"]) == rid
    assert obj["desired_type"] == "LATE"
    assert obj["base_attendance_version"] == 1
    assert obj["initial_status"] == ObjectionInitialStatus.PENDING.value
    assert obj["final_status"] == ObjectionFinalStatus.PENDING.value
    assert obj["file_ids"] == []
    assert _audit_count(session, "objection.create") == 1


def test_create_other_students_record_404(client: TestClient, session: Session) -> None:
    # s1 学生去碰 s2 的考勤：他人记录与不存在统一 404，防枚举。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    _, sh = _student_headers(client, session, sc, "s1")
    r = client.post(
        _create_obj_url(rec_ids[sc["s2"]]),
        headers=sh,
        json={"desired_type": "NORMAL", "reason": "越权"},
    )
    assert r.status_code == 404, r.text


def test_create_missing_record_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _make_student(session, sc, "s1")
    sh = _relogin(client, sc, "s1")
    r = client.post(
        _create_obj_url(999999),
        headers=sh,
        json={"desired_type": "NORMAL", "reason": "无"},
    )
    assert r.status_code == 404, r.text


def test_create_desired_equals_current_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    _, sh = _student_headers(client, session, sc, "s2")  # s2=NORMAL
    r = client.post(
        _create_obj_url(rec_ids[sc["s2"]]),
        headers=sh,
        json={"desired_type": "NORMAL", "reason": "还是正常"},
    )
    assert r.status_code == 422, r.text


def test_create_duplicate_open_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    _, sh = _student_headers(client, session, sc, "s2")
    _create_objection(client, sh, rec_ids[sc["s2"]], desired="LATE")
    r = client.post(
        _create_obj_url(rec_ids[sc["s2"]]),
        headers=sh,
        json={"desired_type": "ABSENT", "reason": "改旷课"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.DUPLICATE_ACTIVE_OBJECTION.value


def test_create_window_closed_conflict(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    rid = rec_ids[sc["s2"]]
    # 回溯考勤生成时刻到 10 天前，并收紧窗口到 1 天 → 超期。
    rec = _record(session, rid)
    rec.created_at = utcnow() - timedelta(days=10)
    session.commit()
    monkeypatch.setenv("OBJECTION_WINDOW_DAYS", "1")
    get_settings.cache_clear()
    try:
        _, sh = _student_headers(client, session, sc, "s2")
        r = client.post(
            _create_obj_url(rid),
            headers=sh,
            json={"desired_type": "LATE", "reason": "过期申诉"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["code"] == ErrorCode.OBJECTION_WINDOW_CLOSED.value
    finally:
        monkeypatch.delenv("OBJECTION_WINDOW_DAYS", raising=False)
        get_settings.cache_clear()


def test_create_bad_proof_file_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    acct, sh = _student_headers(client, session, sc, "s2")
    # 材料不存在（无对应文件行）→ 校验材料非法 422。
    r = client.post(
        _create_obj_url(rec_ids[sc["s2"]]),
        headers=sh,
        json={"desired_type": "LATE", "reason": "有凭证", "file_ids": [987654]},
    )
    assert r.status_code == 422, r.text
    _ = acct


def test_create_links_valid_proof_files(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    acct, sh = _student_headers(client, session, sc, "s2")
    f1 = _make_proof_file(session, uploader_id=acct.id, key="pf1")
    f2 = _make_proof_file(session, uploader_id=acct.id, key="pf2")
    obj = _create_objection(
        client,
        sh,
        rec_ids[sc["s2"]],
        desired="LATE",
        file_ids=[f1.id, f2.id],
    )
    assert sorted(int(x) for x in obj["file_ids"]) == sorted([f1.id, f2.id])


def test_objection_proof_access_follows_review_permission_and_ownership(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    student, sh = _student_headers(client, session, sc, "s2")
    proof = _make_proof_file(session, uploader_id=student.id, key="review-proof")
    unlinked = _make_proof_file(session, uploader_id=student.id, key="unlinked-proof")
    _create_objection(client, sh, rec_ids[sc["s2"]], desired="LATE", file_ids=[proof.id])
    url = f"/api/v1/files/{proof.id}/access"
    assert client.get(url, headers=sh).status_code == 200
    assert client.get(url, headers=h).status_code == 200
    assert client.get(f"/api/v1/files/{unlinked.id}/access", headers=h).status_code == 404

    _, other = _student_headers(client, session, sc, "s1")
    assert client.get(url, headers=other).status_code == 404

    sam = _make_user(session, "proof-reviewer", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam_h = _bearer(_login(client, "proof-reviewer"))
    assert client.get(url, headers=sam_h).status_code == 404
    grant = client.put(
        f"/api/v1/users/{sam.id}/optional-permissions/objection.initial_review",
        headers=h,
        json={"enabled": True, "lockVersion": sam.lock_version, "reason": "负责初核"},
    )
    assert grant.status_code == 200, grant.text
    assert client.get(url, headers=sam_h).status_code == 200
    session.refresh(sam)
    revoke = client.put(
        f"/api/v1/users/{sam.id}/optional-permissions/objection.initial_review",
        headers=h,
        json={"enabled": False, "lockVersion": sam.lock_version, "reason": "收回初核"},
    )
    assert revoke.status_code == 200, revoke.text
    assert client.get(url, headers=sam_h).status_code == 404


# --------------------------------------------------------------------------- #
# 读取范围：OWN vs MANAGE vs 派生 vs 防枚举
# --------------------------------------------------------------------------- #
def test_list_own_scope_only(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    # s1（LATE→NORMAL）与 s2（NORMAL→LATE）各提一条异议。
    _, sh1 = _student_headers(client, session, sc, "s1")
    _create_objection(client, sh1, rec_ids[sc["s1"]], desired="NORMAL")
    _, sh2 = _student_headers(client, session, sc, "s2")
    _create_objection(client, sh2, rec_ids[sc["s2"]], desired="LATE")
    mine = client.get(_OBJS, headers=sh2).json()["data"]
    assert mine["total"] == 1
    assert all(int(i["student_id"]) == sc["s2"] for i in mine["items"])
    full = client.get(_OBJS, headers=h).json()["data"]
    assert full["total"] == 2  # 管理范围见全量


def test_detail_anti_enumeration_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2")
    _, sh1 = _student_headers(client, session, sc, "s1")  # 另一生
    r = client.get(f"{_OBJS}/{oid}", headers=sh1)
    assert r.status_code == 404, r.text
    # 本人可读；管理亦可读。
    sh2 = _relogin(client, sc, "s2")
    assert client.get(f"{_OBJS}/{oid}", headers=sh2).status_code == 200
    assert client.get(f"{_OBJS}/{oid}", headers=h).status_code == 200


def test_sam_default_cannot_read_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _open_objection(client, h, session, sc, which="s2")
    _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam = _bearer(_login(client, "sam"))
    r = client.get(_OBJS, headers=sam)
    assert r.status_code == 403, r.text


def test_unbound_student_cannot_list_all_objections(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _open_objection(client, h, session, sc, which="s2")
    _make_user(session, "unbound", [RoleCode.STUDENT.value])
    response = client.get(_OBJS, headers=_bearer(_login(client, "unbound")))
    assert response.status_code == 403, response.text


def test_sam_derived_read_after_initial_review_grant(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _open_objection(client, h, session, sc, which="s2")
    sam = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam_h = _bearer(_login(client, "sam"))
    assert client.get(_OBJS, headers=sam_h).status_code == 403  # 默认无读取路径
    # 超管授予可选 objection.initial_review → 派生管理读取。
    r = client.put(
        f"/api/v1/users/{sam.id}/optional-permissions/objection.initial_review",
        headers=h,
        json={"enabled": True, "lockVersion": sam.lock_version, "reason": "兼做初核"},
    )
    assert r.status_code == 200, r.text
    # 令牌权限每次现取：重新登录后读到授予后的范围（SameUser 会话权限即时生效亦可）。
    sam_h2 = _bearer(_login(client, "sam"))
    listed = client.get(_OBJS, headers=sam_h2).json()["data"]
    assert listed["total"] == 1  # 管理范围
    # 关闭初核 → 失去派生读取来源。
    after = session.execute(select(UserAccount).where(UserAccount.id == sam.id)).scalar_one()
    session.refresh(after)
    r2 = client.put(
        f"/api/v1/users/{sam.id}/optional-permissions/objection.initial_review",
        headers=h,
        json={"enabled": False, "lockVersion": after.lock_version, "reason": "收回"},
    )
    assert r2.status_code == 200, r2.text
    sam_h3 = _bearer(_login(client, "sam"))
    assert client.get(_OBJS, headers=sam_h3).status_code == 403


# --------------------------------------------------------------------------- #
# 初核：不改考勤
# --------------------------------------------------------------------------- #
def test_initial_review_needs_permission_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2")
    sh = _relogin(client, sc, "s2")
    r = client.post(_initial_url(oid), headers=sh, json={"decision": "PASSED"})
    assert r.status_code == 403, r.text


def test_initial_review_pass_keeps_attendance(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, rid = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    r = client.post(
        _initial_url(oid), headers=h, json={"decision": "PASSED", "comment": "建议支持"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["initial_status"] == ObjectionInitialStatus.PASSED.value
    # 初核绝不改考勤：认定仍 NORMAL、版本仍 1。
    rec = _record(session, rid)
    assert rec.effective_type == AttendanceType.NORMAL.value
    assert rec.current_version == 1
    assert _audit_count(session, "objection.initial_review") == 1


def test_initial_review_twice_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2")
    assert client.post(_initial_url(oid), headers=h, json={"decision": "PASSED"}).status_code == 200
    r = client.post(_initial_url(oid), headers=h, json={"decision": "REJECTED"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.STATE_CONFLICT.value


# --------------------------------------------------------------------------- #
# 终审：驳回 / 更正 / 版本冲突 / 权限 / 幂等
# --------------------------------------------------------------------------- #
def test_final_review_reject_keeps_attendance(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, rid = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    r = client.post(
        _final_url(oid),
        headers=h,
        json={"decision": "REJECTED", "comment": "核查不实", "current_version": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["final_status"] == ObjectionFinalStatus.REJECTED.value
    rec = _record(session, rid)
    assert rec.effective_type == AttendanceType.NORMAL.value
    assert rec.current_version == 1
    assert len(_versions(session, rid)) == 1  # 仅初始 SUBMISSION 版本


def test_final_review_approve_corrects_attendance(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, rid = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    # 先初核（可选，终审不强依赖），再终审通过并更正为 LATE。
    assert client.post(_initial_url(oid), headers=h, json={"decision": "PASSED"}).status_code == 200
    r = client.post(
        _final_url(oid),
        headers=h,
        json={
            "decision": "APPROVED",
            "final_type": "LATE",
            "comment": "属实改判",
            "current_version": 1,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["final_status"] == ObjectionFinalStatus.APPROVED.value
    assert r.json()["data"]["final_attendance_type"] == "LATE"
    rec = _record(session, rid)
    assert rec.effective_type == AttendanceType.LATE.value
    assert rec.current_version == 2
    vers = _versions(session, rid)
    assert [v.version_no for v in vers] == [1, 2]
    assert vers[1].source_type == AttendanceSourceType.OBJECTION_FINAL.value
    assert vers[1].attendance_type == AttendanceType.LATE.value
    assert int(vers[1].source_id) == oid
    assert _audit_count(session, "objection.final_review") == 1


def test_final_review_approve_no_correction(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, rid = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    # 终审通过但维持 NORMAL（与当前一致）→ 关闭异议、不改考勤不追加版本。
    r = client.post(
        _final_url(oid),
        headers=h,
        json={"decision": "APPROVED", "final_type": "NORMAL", "current_version": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["final_attendance_type"] == "NORMAL"
    rec = _record(session, rid)
    assert rec.effective_type == AttendanceType.NORMAL.value
    assert rec.current_version == 1
    assert len(_versions(session, rid)) == 1


def test_final_review_approve_missing_final_type_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2")
    r = client.post(_final_url(oid), headers=h, json={"decision": "APPROVED", "current_version": 1})
    assert r.status_code == 422, r.text


def test_final_review_version_conflict(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, rid = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    # 异议发起后，他人先更正考勤（version 1→2），使 record.current_version ≠ base。
    assert (
        client.post(
            f"{_ATT}/{rid}/corrections",
            headers=h,
            json={"attendance_type": "ABSENT", "reason": "先更正", "current_version": 1},
        ).status_code
        == 200
    )
    r = client.post(
        _final_url(oid),
        headers=h,
        json={"decision": "APPROVED", "final_type": "LATE", "current_version": 2},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.VERSION_CONFLICT.value
    # 不覆盖他人新认定：考勤仍为更正后的 ABSENT、version 2。
    rec = _record(session, rid)
    assert rec.effective_type == AttendanceType.ABSENT.value
    assert rec.current_version == 2


def test_final_review_twice_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2", desired="LATE")
    assert (
        client.post(
            _final_url(oid), headers=h, json={"decision": "REJECTED", "current_version": 1}
        ).status_code
        == 200
    )
    r = client.post(
        _final_url(oid),
        headers=h,
        json={"decision": "APPROVED", "final_type": "LATE", "current_version": 1},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.STATE_CONFLICT.value


def test_sam_cannot_final_review_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    oid, _ = _open_objection(client, h, session, sc, which="s2")
    sam = _make_user(session, "sam", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    client.put(
        f"/api/v1/users/{sam.id}/optional-permissions/objection.initial_review",
        headers=h,
        json={"enabled": True, "lockVersion": sam.lock_version, "reason": "初核"},
    )
    sam_h = _bearer(_login(client, "sam"))
    # 即便被授予初核（派生管理读取），仍无终审权限。
    r = client.post(
        _final_url(oid), headers=sam_h, json={"decision": "REJECTED", "current_version": 1}
    )
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# 并发：同一考勤双人同时创建，恰一成功
# --------------------------------------------------------------------------- #
def _create_worker(
    engine, actor_id: int, sid: int, record_id: int, barrier, out: dict, idx: int
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id,
            username=f"c{idx}",
            display_name=f"c{idx}",
            status=UserStatus.ACTIVE.value,
            roles=[RoleCode.STUDENT.value],
            permissions=[],
        )
        from app.modules.objection.schemas import ObjectionCreateRequest

        req = ObjectionCreateRequest(desired_type="LATE", reason=f"并发{idx}")  # noqa: ARG001
        barrier.wait()
        # 学生 id 需与考勤归属匹配：service 依 account.student_id 解析，故 actor_id 对应 sid。
        ObjectionService(s).create(actor, record_id, req, f"conc-{idx}")
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()
    _ = sid


def test_concurrent_duplicate_objection_one_wins(
    client: TestClient, engine: Engine, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    rid = rec_ids[sc["s2"]]
    acct = _make_student(session, sc, "s2")  # 一个学生账号，两线程以同一身份并发创建
    session.commit()
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(
            target=_create_worker, args=(engine, acct.id, sc["s2"], rid, barrier, out, i)
        )
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    oks = [v for v in out.values() if v[0] == "ok"]
    errs = [v for v in out.values() if v[0] == "error"]
    assert len(oks) == 1, out
    assert len(errs) == 1, out
    assert "ConflictError" in errs[0][1], out
    session.commit()
    session.expire_all()
    open_objs = (
        session.execute(select(Objection).where(Objection.attendance_record_id == rid))
        .scalars()
        .all()
    )
    assert len(open_objs) == 1


# --------------------------------------------------------------------------- #
# 清理耦合：未完成异议暂停到期清理，关闭后重新纳入
# --------------------------------------------------------------------------- #
def _make_proof_file(
    session: Session,
    *,
    uploader_id: int,
    key: str,
    status: str = FileStatus.READY.value,
    expires_in_hours: int | None = None,
    category: str = FileCategory.OBJECTION_PROOF.value,
) -> FileObject:
    now = utcnow()
    row = FileObject(
        object_key=key,
        category=category,
        original_name=f"{key}.png",
        content_type="image/png",
        size_bytes=10,
        sha256="b" * 64,
        uploader_user_id=uploader_id,
        status=status,
        retention_policy_version=1,
        expires_at=(now + timedelta(hours=expires_in_hours))
        if expires_in_hours is not None
        else None,
    )
    session.add(row)
    session.commit()
    session.expire_all()
    return row


def test_open_objection_pauses_purge_until_closed(
    client: TestClient, session: Session, tmp_path: Path
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    acct, sh = _student_headers(client, session, sc, "s2")
    f = _make_proof_file(session, uploader_id=acct.id, key="purge1", expires_in_hours=+24)
    obj = _create_objection(client, sh, rec_ids[sc["s2"]], desired="LATE", file_ids=[f.id])
    oid = int(obj["id"])
    # 令材料到期（回溯 expires_at 到过去）。
    session.refresh(f)
    f.expires_at = utcnow() - timedelta(hours=1)
    session.commit()

    store: Any = LocalStorage(str(tmp_path / "store"), secret="test-secret")
    store.save("purge1", b"proof-bytes", "image/png")
    svc = FileService(session, storage=store)
    admin = session.execute(select(UserAccount).where(UserAccount.username == "admin")).scalar_one()
    reviewer = CurrentUser(
        id=admin.id,
        username=admin.username,
        display_name=admin.display_name,
        status=admin.status,
        roles=[RoleCode.SUPER_ADMIN.value],
        permissions=["objection.final_review"],
    )
    access = svc.get_access(reviewer, f.id)
    query = parse_qs(urlsplit(access.url).query)
    content, content_type, _ = svc.download(f.id, int(query["expires"][0]), query["sig"][0])
    assert (content, content_type) == (b"proof-bytes", "image/png")
    # 被未完成异议引用 → 排除于候选，scanned 0、不动。
    blocked = svc.purge_expired_files()
    assert blocked["scanned"] == 0
    session.expire_all()
    assert session.get(FileObject, f.id).status == FileStatus.READY.value  # type: ignore[union-attr]

    # 关闭异议（终审驳回）→ 材料重新纳入并清理。
    assert (
        client.post(
            _final_url(oid), headers=h, json={"decision": "REJECTED", "current_version": 1}
        ).status_code
        == 200
    )
    # 终审由 HTTP 会话提交；夹具会话须结束旧事务开新快照方可见异议已关闭。
    session.commit()
    session.expire_all()
    after = svc.purge_expired_files()
    assert after["scanned"] == 1
    assert after["purged"] == 1
    session.expire_all()
    assert session.get(FileObject, f.id).status == FileStatus.PURGED.value  # type: ignore[union-attr]
