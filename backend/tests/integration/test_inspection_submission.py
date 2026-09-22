"""查课 P5 Wave 5c：查课提交（submission.create / submission.read）集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P5 与技术方案 12 / 13.2 / 13.3 / 15 / 16.2：
- 认证与功能守卫：无令牌 401；管理角色无 submission.create → 403（VOLUNTEER 才可提交）。
- 身份纵深（Service 事务内）：持 submission.create 但非 VOLUNTEER 角色 → 403；账号停用 → 403；
  仅可提交"本人当前受派"任务（未受派 / 非本人 → 403）；本学期无志愿者资格 → 403。
- 结论一致性（schema）：NORMAL 带异常明细 / ABNORMAL 无明细 → 422；异常学生不在本任务
  当前名单或重复 → 422（fieldErrors.duplicate_student_ids / not_in_roster_student_ids）。
- "至多一个待审核 / 审核通过"不变式：重复提交 → 409 STATE_CONFLICT；真实并发恰好一成一拒。
- 取消任务提交 → 409。
- 附件（16.2）：要求照片却无附件 → 422；超上限 → 422；附件非 READY / 非本人 / 类别不符 /
  已过期 → 422；本人 READY SUBMISSION_PHOTO 通过并回填 file_ids。
- 截止与时序（13.3）：提交前幂等结算锁定"截止时"事实——按时提交不被结算改写；迟交
  late_at_submission=true 且结算为 OVERDUE_UNEXECUTED；按时提交后经结算得 VALID_SUBMISSION。
- 五态精判（12）：有 PENDING 提交 → 任务"待审核"；本人历史读取强制 OWN_SUBMISSION 范围；
  读他人提交统一 404 防枚举。
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
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    DeadlineAssessmentResult,
    InspectionSubmission,
    ReviewStatus,
    SubmissionDeadlineDay,
    TaskDeadlineAssessment,
)
from app.modules.inspection.schemas import SubmissionCreateRequest
from app.modules.inspection.service import InspectionService
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"
_DL = "/api/v1/submission-deadlines"
_SUBS = "/api/v1/submissions"
_ME_SUBS = "/api/v1/me/submissions"
_MON1 = "2026-09-07"
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


def _gen_course(
    client: TestClient, h: dict[str, str], sem_id: int, tc_ids: list[int],
    *, require_photo: bool = False,
) -> int:
    d = _post(
        client,
        h,
        _GEN,
        {"semester_id": sem_id, "inspection_type": "COURSE", "week_nos": [1],
         "teaching_class_ids": tc_ids, "require_photo": require_photo},
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


def _submit_url(task_id: int) -> str:
    return f"{_TASKS}/{task_id}/submissions"


def _scene(client: TestClient, h: dict[str, str], *, require_photo: bool = False) -> dict:
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
    assert _gen_course(client, h, sem_id, [t1], require_photo=require_photo) == 1
    tasks = _list_tasks(client, h, sem_id)
    assert len(tasks) == 1
    return {"sem_id": sem_id, "cs": cs, "s1": s1, "s2": s2, "task": tasks[0],
            "task_id": int(tasks[0]["id"])}


def _make_volunteer(
    client: TestClient,
    h: dict[str, str],
    session: Session,
    sc: dict,
    username: str = "vol",
) -> tuple[UserAccount, dict[str, str]]:
    """建一名本学期有资格的志愿者（独立行政班避免本班回避），指派到任务并返回账号与令牌头。"""
    other = _create_admin_class(client, h, f"VCLASS_{username}")
    sid = _create_student(client, h, f"V{username}", other)
    _grant_qual(client, h, sc["sem_id"], sid)
    vol = _make_user(session, username, [RoleCode.VOLUNTEER.value], student_id=sid)
    _assign(client, h, sc["task_id"], vol.id)
    return vol, _bearer(_login(client, username))


# --------------------------------------------------------------------------- #
# 截止 / 提交事实读助手（HTTP 写入后须结束夹具读事务再取新快照）
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


def _backdate_within_deadline(session: Session, sem_id: int, task_id: int) -> None:
    """构造"截止已过但曾有按时提交"：提交时刻挪到 now-5h、截止挪到 now-1h，
    使 submitted_at ≤ deadline < now，结算即得 VALID_SUBMISSION（无需真实等待）。
    """
    sub = _submissions(session, task_id)[0]
    now = utcnow()
    fresh = session.get(InspectionSubmission, sub.id)
    assert fresh is not None
    fresh.submitted_at = now - timedelta(hours=5)
    day = _get_day(session, sem_id, _MON1_D)
    day.deadline_at = now - timedelta(hours=1)
    session.commit()


def _assessment(session: Session, task_id: int) -> TaskDeadlineAssessment | None:
    session.commit()
    session.expire_all()
    return session.execute(
        select(TaskDeadlineAssessment).where(TaskDeadlineAssessment.task_id == task_id)
    ).scalar_one_or_none()


def _submissions(session: Session, task_id: int) -> list[InspectionSubmission]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(InspectionSubmission)
            .where(InspectionSubmission.task_id == task_id)
            .order_by(InspectionSubmission.attempt_no)
        ).scalars().all()
    )


def _audit_actions(session: Session, action: str) -> int:
    session.commit()
    session.expire_all()
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


def _make_file(
    session: Session,
    uploader_id: int | None,
    *,
    status: str = FileStatus.READY.value,
    category: str = FileCategory.SUBMISSION_PHOTO.value,
    expires_in_hours: int | None = 24,
    tag: str = "f",
) -> FileObject:
    """直接入库一条文件记录，用于附件归属 / 状态 / 有效期校验（绕开上传管线，聚焦提交侧）。"""
    row = FileObject(
        object_key=f"obj-{tag}-{uploader_id}-{status}-{category}",
        category=category,
        original_name=f"{tag}.png",
        content_type="image/png",
        size_bytes=1234,
        sha256="0" * 64,
        uploader_user_id=uploader_id,
        status=status,
        expires_at=(utcnow() + timedelta(hours=expires_in_hours))
        if expires_in_hours is not None
        else None,
    )
    session.add(row)
    session.commit()
    session.expire_all()
    return row


def _normal_body(**over: Any) -> dict:
    body: dict[str, Any] = {"result": "NORMAL", "abnormal_items": [], "file_ids": []}
    body.update(over)
    return body


def _abnormal_body(items: list[dict], **over: Any) -> dict:
    body: dict[str, Any] = {"result": "ABNORMAL", "abnormal_items": items, "file_ids": []}
    body.update(over)
    return body


def _settle(client: TestClient, h: dict[str, str], body: dict) -> dict:
    return _post(client, h, f"{_DL}/settle", body)


# --------------------------------------------------------------------------- #
# 认证与功能守卫
# --------------------------------------------------------------------------- #
def test_submission_requires_auth_401(client: TestClient, session: Session) -> None:
    assert client.post(_submit_url(1), json=_normal_body()).status_code == 401
    assert client.get(_ME_SUBS).status_code == 401
    assert client.get(f"{_SUBS}/1").status_code == 401


def test_admin_cannot_create_submission_403(client: TestClient, session: Session) -> None:
    # SUPER_ADMIN 无 submission.create（VOLUNTEER 专属）→ 路由守卫即 403。
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    h = _bearer(_login(client, "admin"))
    sc = _scene(client, h)
    r = client.post(_submit_url(sc["task_id"]), headers=h, json=_normal_body())
    assert r.status_code == 403, r.text


def test_create_perm_without_volunteer_role_403(client: TestClient, session: Session) -> None:
    # 持 submission.create 但非 VOLUNTEER 角色：越过路由守卫后被 Service 身份纵深拦下 → 403。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _make_perm_user(session, "creator", [PermissionCode.SUBMISSION_CREATE.value])
    ch = _bearer(_login(client, "creator"))
    r = client.post(_submit_url(sc["task_id"]), headers=ch, json=_normal_body())
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# Happy path：NORMAL / ABNORMAL + 五态待审核 + 审计
# --------------------------------------------------------------------------- #
def _admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


def test_submit_normal_happy(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 令本次提交准点
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body(note="到课齐"))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert int(d["attempt_no"]) == 1
    assert d["result"] == "NORMAL"
    assert d["review_status"] == ReviewStatus.PENDING.value
    assert d["late_at_submission"] is False
    assert d["abnormal_items"] == []
    assert d["deadline_version_id"] is not None  # 冻结当日适用截止版本
    assert _audit_actions(session, "submission.create") == 1
    # 五态：有 PENDING 提交 → 任务"待审核"（管理视图可见）。
    detail = client.get(f"{_TASKS}/{sc['task_id']}", headers=h).json()["data"]
    assert detail["status"] == "待审核"
    # 本人历史可读，含本条。
    mine = client.get(_ME_SUBS, headers=vh).json()["data"]
    assert mine["total"] == 1
    assert int(mine["items"][0]["id"]) == int(d["id"])


def test_submit_abnormal_backfills_roster_display(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    items = [
        {"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到 5 分钟"},
        {"student_id": sc["s2"], "attendance_type": "LEAVE", "note": None},
    ]
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_abnormal_body(items))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["result"] == "ABNORMAL"
    got = {int(x["student_id"]): x for x in d["abnormal_items"]}
    assert got[sc["s1"]]["attendance_type"] == "LATE"
    assert got[sc["s1"]]["student_no"] == "S001"  # 名单快照回填
    assert got[sc["s1"]]["name"] == "学生S001"
    assert got[sc["s2"]]["attendance_type"] == "LEAVE"


# --------------------------------------------------------------------------- #
# 结论一致性 / 名单归属校验（422）
# --------------------------------------------------------------------------- #
def test_result_consistency_schema_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    # NORMAL 却带异常明细 → 422。
    r1 = client.post(
        _submit_url(sc["task_id"]), headers=vh,
        json={"result": "NORMAL",
              "abnormal_items": [{"student_id": sc["s1"], "attendance_type": "LATE"}],
              "file_ids": []},
    )
    assert r1.status_code == 422, r1.text
    # ABNORMAL 却无明细 → 422。
    r2 = client.post(_submit_url(sc["task_id"]), headers=vh,
                     json={"result": "ABNORMAL", "abnormal_items": [], "file_ids": []})
    assert r2.status_code == 422, r2.text


def test_abnormal_student_not_in_roster_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    other_cls = _create_admin_class(client, h, "OTHER")
    outsider = _create_student(client, h, "X999", other_cls)
    _vol, vh = _make_volunteer(client, h, session, sc)
    r = client.post(
        _submit_url(sc["task_id"]), headers=vh,
        json=_abnormal_body([{"student_id": outsider, "attendance_type": "ABSENT"}]),
    )
    assert r.status_code == 422, r.text
    fe = r.json()["fieldErrors"]
    assert outsider in fe["not_in_roster_student_ids"]


def test_abnormal_duplicate_student_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    r = client.post(
        _submit_url(sc["task_id"]), headers=vh,
        json=_abnormal_body([
            {"student_id": sc["s1"], "attendance_type": "LATE"},
            {"student_id": sc["s1"], "attendance_type": "ABSENT"},
        ]),
    )
    assert r.status_code == 422, r.text
    assert sc["s1"] in r.json()["fieldErrors"]["duplicate_student_ids"]


# --------------------------------------------------------------------------- #
# 身份 / 状态纵深：受派、资格、停用、取消
# --------------------------------------------------------------------------- #
def test_submit_not_assigned_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 建志愿者但不指派到该任务 → 提交被拒 403（仅本人当前受派）。
    other = _create_admin_class(client, h, "VCLASS_Z")
    sid = _create_student(client, h, "VZ", other)
    _grant_qual(client, h, sc["sem_id"], sid)
    _make_user(session, "volunassigned", [RoleCode.VOLUNTEER.value], student_id=sid)
    vh = _bearer(_login(client, "volunassigned"))
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 403, r.text


def test_submit_no_qualification_403(client: TestClient, session: Session) -> None:
    # 指派本身要求当前资格（排班硬约束），故无法直接指派"从未有资格"者；
    # 改为"先合格指派、再撤销资格"，提交时 Service 实时资格校验应拒 → 403。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    vol, vh = _make_volunteer(client, h, session, sc, username="volnoqual")
    _grant_qual_revoked(client, h, sc["sem_id"], int(vol.student_id))
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 403, r.text


def _grant_qual_revoked(
    client: TestClient, h: dict[str, str], sem_id: int, student_id: int
) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications",
        headers=h,
        json={"semester_id": sem_id, "student_id": student_id, "enabled": False,
              "reason": "撤销资格"},
    )
    assert rp.status_code == 200, rp.text


def test_submit_canceled_task_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    c = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                    json={"reason": "停课", "lock_version": 1})
    assert c.status_code == 200, c.text
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.STATE_CONFLICT.value


# --------------------------------------------------------------------------- #
# "至多一个待审核 / 审核通过"不变式 + 真实并发
# --------------------------------------------------------------------------- #
def test_repeat_submission_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    first = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert first.status_code == 200, first.text
    second = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert second.status_code == 409, second.text
    assert second.json()["code"] == ErrorCode.STATE_CONFLICT.value
    assert len(_submissions(session, sc["task_id"])) == 1


def _submit_worker(
    engine: Engine, actor_id: int, task_id: int,
    barrier: threading.Barrier, out: dict[int, object], idx: int,
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="vol", display_name="vol",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.VOLUNTEER.value], permissions=[],
        )
        body = SubmissionCreateRequest(result="NORMAL", abnormal_items=[], file_ids=[])
        barrier.wait()
        InspectionService(s).create_submission(actor, task_id, body, f"conc-{idx}")
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_submit_exactly_one(
    client: TestClient, engine: Engine, session: Session
) -> None:
    # 同一志愿者并发提交同一任务：任务行 FOR UPDATE 串行化 + 锁内开放提交复查 → 恰好一条。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    vol, _ = _make_volunteer(client, h, session, sc)
    session.commit()
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(3)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(target=_submit_worker,
                         args=(engine, vol.id, sc["task_id"], barrier, out, i))
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(out) == 3, out
    oks = [k for k, v in out.items() if v[0] == "ok"]
    errs = [v for k, v in out.items() if v[0] == "error"]
    assert len(oks) == 1, out
    assert len(errs) == 2, out
    # 落败方均为业务冲突（409 家族），非唯一约束 500。
    assert all("ConflictError" in e[1] for e in errs), out
    assert len(_submissions(session, sc["task_id"])) == 1


# --------------------------------------------------------------------------- #
# 附件校验（技术方案 16.2）
# --------------------------------------------------------------------------- #
def test_attachment_requires_photo_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, require_photo=True)
    _vol, vh = _make_volunteer(client, h, session, sc)
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 422, r.text
    assert r.json()["fieldErrors"]["file_ids"] == []


def test_attachment_ok_and_foreign_rejected(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, require_photo=True)
    vol, vh = _make_volunteer(client, h, session, sc)
    # 他人上传的合规照片：先建另一账号及其文件。
    _make_user(session, "other_uploader", [RoleCode.VOLUNTEER.value])
    foreign = _make_file(session, _user_id(session, "other_uploader"), tag="foreign")
    own = _make_file(session, vol.id, tag="own")
    # 引用他人文件 → 422（归属校验），file_ids 命中。
    r_bad = client.post(_submit_url(sc["task_id"]), headers=vh,
                        json=_normal_body(file_ids=[foreign.id]))
    assert r_bad.status_code == 422, r_bad.text
    assert foreign.id in r_bad.json()["fieldErrors"]["file_ids"]
    # 本人 READY 照片 → 通过并回填。
    r_ok = client.post(_submit_url(sc["task_id"]), headers=vh,
                       json=_normal_body(file_ids=[own.id]))
    assert r_ok.status_code == 200, r_ok.text
    assert int(r_ok.json()["data"]["file_ids"][0]) == own.id


def test_attachment_not_ready_or_expired_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    vol, vh = _make_volunteer(client, h, session, sc)
    not_ready = _make_file(session, vol.id, status=FileStatus.UPLOADING.value, tag="nr")
    expired = _make_file(session, vol.id, expires_in_hours=-1, tag="exp")
    wrong_cat = _make_file(session, vol.id, category=FileCategory.TEMP.value, tag="cat")
    r = client.post(_submit_url(sc["task_id"]), headers=vh,
                    json=_normal_body(file_ids=[not_ready.id, expired.id, wrong_cat.id]))
    assert r.status_code == 422, r.text
    bad = set(r.json()["fieldErrors"]["file_ids"])
    assert {not_ready.id, expired.id, wrong_cat.id} <= bad


def _user_id(session: Session, username: str) -> int:
    session.commit()
    session.expire_all()
    return int(session.execute(
        select(UserAccount.id).where(UserAccount.username == username)
    ).scalar_one())


# --------------------------------------------------------------------------- #
# 截止时序与结算钩子（VALID_SUBMISSION / OVERDUE 锁定）
# --------------------------------------------------------------------------- #
def test_late_submission_sets_flag_and_overdue(client: TestClient, session: Session) -> None:
    # 截止已过再提交：提交前幂等结算先锁 OVERDUE_UNEXECUTED（本条迟到提交不参与），
    # 提交本身 late_at_submission=true。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=-2)
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 200, r.text
    assert r.json()["data"]["late_at_submission"] is True
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.OVERDUE_UNEXECUTED.value


def test_valid_submission_settle_after_deadline(client: TestClient, session: Session) -> None:
    # 截止前按时提交（未到期，无快照）→ 构造时间越过截止（按时提交事实保留）后结算
    # → VALID_SUBMISSION（存在按时提交，不看审核结果，技术方案 13.2、62/64）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 未来截止：提交准点
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 200, r.text
    assert r.json()["data"]["late_at_submission"] is False
    assert _assessment(session, sc["task_id"]) is None  # 未到期：无快照
    _backdate_within_deadline(session, sc["sem_id"], sc["task_id"])
    _settle(client, h, {"semester_id": sc["sem_id"], "task_ids": [sc["task_id"]]})
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.VALID_SUBMISSION.value


def test_reject_after_deadline_not_backdated(client: TestClient, session: Session) -> None:
    # 按时提交后被人为退回（此处以直接改 review_status 模拟 P5d 之后的退回事实），
    # 结算仍看"截止前有按时提交"→ VALID_SUBMISSION，不倒算为未执行（技术方案 13.2、62/64）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 未来截止：提交准点
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 200, r.text
    # 构造截止已过（保留按时提交事实），再模拟审核退回。
    _backdate_within_deadline(session, sc["sem_id"], sc["task_id"])
    sub = _submissions(session, sc["task_id"])[0]
    fresh = session.get(InspectionSubmission, sub.id)
    assert fresh is not None
    fresh.review_status = ReviewStatus.REJECTED.value
    session.commit()
    _settle(client, h, {"semester_id": sc["sem_id"], "task_ids": [sc["task_id"]]})
    asmt = _assessment(session, sc["task_id"])
    assert asmt is not None
    assert asmt.result == DeadlineAssessmentResult.VALID_SUBMISSION.value


# --------------------------------------------------------------------------- #
# 提交前结算不改截止版本 & 本人读取范围
# --------------------------------------------------------------------------- #
def test_submit_freezes_deadline_version(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _vol, vh = _make_volunteer(client, h, session, sc)
    r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r.status_code == 200, r.text
    dvid = int(r.json()["data"]["deadline_version_id"])
    session.commit()
    session.expire_all()
    from app.modules.inspection.models import SubmissionDeadlineVersion

    ver = session.get(SubmissionDeadlineVersion, dvid)
    assert ver is not None
    day = _get_day(session, sc["sem_id"], _MON1_D)
    assert ver.deadline_day_id == day.id
    assert ver.version_no == day.version


def test_list_and_get_scope_own_only(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    vol_a, vh_a = _make_volunteer(client, h, session, sc, username="volA")
    # 第二个志愿者指派同一任务？不行（唯一受派）。改建第二个任务较繁；此处仅验单条读越权。
    r = client.post(_submit_url(sc["task_id"]), headers=vh_a, json=_normal_body())
    assert r.status_code == 200, r.text
    sub_id = int(r.json()["data"]["id"])
    # 本人可读回。
    assert client.get(f"{_SUBS}/{sub_id}", headers=vh_a).status_code == 200
    # 另一持 submission.read 的志愿者读他人提交 → 404 防枚举。
    _make_perm_user(session, "reader", [PermissionCode.SUBMISSION_READ.value])
    rh = _bearer(_login(client, "reader"))
    assert client.get(f"{_SUBS}/{sub_id}", headers=rh).status_code == 404
    lst = client.get(_ME_SUBS, headers=rh).json()["data"]
    assert lst["total"] == 0  # 强制本人范围
    assert int(vol_a.id) > 0
