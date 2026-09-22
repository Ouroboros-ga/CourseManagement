"""查课 P5 Wave 5d：提交审核 + 考勤读取/更正 + 应到人数调整，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P5 与技术方案 12 / 13.3 / 14 / 15、PERMISSIONS.md 7 / 12.8：
- 审核守卫与鉴权：无令牌 401；志愿者无 submission.review → 403。
- 通过生成考勤（12）：ABNORMAL→列异常者取明细类型、未列者 NORMAL，各建 version 1
  来源 SUBMISSION；NORMAL→全 NORMAL；任务五态转"已完成"；写审计。
- 驳回保留事实（12）：REJECTED 不生成考勤，原提交与照片保留，志愿者可再生成下一 attempt。
- 幂等与并发：重复审核 → 409；双人同审恰好一人成功、考勤不重复；审核 vs 取消都锁任务，
  恰一成功且状态互斥（不会出现既取消又有考勤）。
- 取消守卫（51）：审核通过（已生成考勤）后取消 → 409；未通过前取消 → PENDING 提交审核 409。
- 考勤读取范围（7、12.8）：GET /attendance 仅管理范围（志愿者/学生越权 403）；
  /me/attendance 强制本人；详情/版本按范围，越权统一 404 防枚举。
- 更正（14、15）：current_version 条件更新 + 追加 CORRECTION 版本；陈旧版本 → 409；
  志愿者/学生无 attendance.correct → 403。
- 应到人数调整（14）：非负、不得小于当前异常认定数（422）、乐观锁（409）、需专门权限（403）。
"""

from __future__ import annotations

import threading
from datetime import date as date_
from datetime import timedelta
from typing import Any

import pytest
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
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Permission, Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import (
    InspectionSubmission,
    InspectionTask,
    ReviewStatus,
    SubmissionDeadlineDay,
)
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
_SUBS = "/api/v1/submissions"
_ATT = "/api/v1/attendance"
_ME_ATT = "/api/v1/me/attendance"
_MON1 = "2026-09-07"
_MON1_D = date_(2026, 9, 7)


# --------------------------------------------------------------------------- #
# 装配助手（与 test_inspection_submission 同构，令本文件自包含）
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


def _admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


def _create_admin_class(client: TestClient, h: dict[str, str], code: str) -> int:
    d = _post(
        client, h, f"{_ACA}/administrative-classes",
        {"class_code": code, "class_name": f"班{code}", "college": "计算机学院",
         "grade_year": 2024},
    )
    return int(d["id"])


def _create_student(client: TestClient, h: dict[str, str], no: str, class_id: int) -> int:
    d = _post(
        client, h, f"{_ACA}/students",
        {"student_no": no, "name": f"学生{no}", "administrative_class_id": class_id},
    )
    return int(d["id"])


def _create_course(client: TestClient, h: dict[str, str], code: str) -> int:
    return int(_post(client, h, f"{_ACA}/courses",
                     {"course_code": code, "course_name": f"课程{code}"})["id"])


def _create_tc(client, h, sem_id: int, course_id: int, code: str) -> int:
    d = _post(
        client, h, f"{_ACA}/teaching-classes",
        {
            "semester_id": sem_id,
            "course_id": course_id,
            "class_code": code,
            "class_name": f"班{code}",
        },
    )
    return int(d["id"])


def _enroll(client, h, tc_id: int, student_ids: list[int]) -> None:
    rp = client.put(f"{_ACA}/teaching-classes/{tc_id}/students", headers=h,
                    json={"student_ids": student_ids})
    assert rp.status_code == 200, rp.text


def _schedule(client, h, tc_id: int, start: int, end: int, classroom: str) -> int:
    d = _post(
        client, h, f"{_ACA}/course-schedules",
        {"teaching_class_id": tc_id, "weekday": 1, "start_period": start, "end_period": end,
         "classroom": classroom, "weeks": [1]},
    )
    return int(d["id"])


def _gen_course(client, h, sem_id: int, tc_ids: list[int]) -> int:
    d = _post(
        client, h, _GEN,
        {"semester_id": sem_id, "inspection_type": "COURSE", "week_nos": [1],
         "teaching_class_ids": tc_ids},
    )
    return int(d["created"])


def _list_tasks(client, h, sem_id: int) -> list[dict[str, Any]]:
    resp = client.get(_TASKS, headers=h, params={"semester_id": sem_id, "limit": 50})
    assert resp.status_code == 200, resp.text
    return list(resp.json()["data"]["items"])


def _grant_qual(client, h, sem_id: int, student_id: int) -> None:
    rp = client.put(
        f"{_ACA}/volunteer-qualifications", headers=h,
        json={"semester_id": sem_id, "student_id": student_id, "enabled": True, "reason": "合格"},
    )
    assert rp.status_code == 200, rp.text


def _assign(client, h, task_id: int, vol_id: int, version: int = 0) -> None:
    resp = client.put(f"{_TASKS}/{task_id}/assignment", headers=h,
                      json={"volunteer_user_id": vol_id, "lock_version": version})
    assert resp.status_code == 200, resp.text


def _scene(client: TestClient, h: dict[str, str]) -> dict:
    """ACTIVE 学期 + 被查班 CS2401(两生 S001/S002) + 教学班 T1，生成 1 任务、1 日截止。"""
    sem = _post(
        client, h, f"{_ACA}/semesters",
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
    return {"sem_id": sem_id, "cs": cs, "s1": s1, "s2": s2,
            "task_id": int(tasks[0]["id"]), "task": tasks[0]}


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
    """经"志愿者提交"造一条 PENDING 提交，返回 submission_id。"""
    _shift_deadline(session, sc["sem_id"], _MON1_D, hours=+48)  # 令提交准点、无到期快照
    username = f"vol{sc['task_id']}{'abn' if abnormal else ''}"
    _vol, vh = _make_volunteer(client, h, session, sc, username=username)
    if abnormal:
        items = [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}]
        r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_abnormal_body(items))
    else:
        r = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body(note="齐"))
    assert r.status_code == 200, r.text
    return int(r.json()["data"]["id"])


# --------------------------------------------------------------------------- #
# 事实读助手（HTTP 写后结束夹具读事务再取新快照）
# --------------------------------------------------------------------------- #
def _records(session: Session, task_id: int) -> list[AttendanceRecord]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(AttendanceRecord).where(AttendanceRecord.task_id == task_id).order_by(
                AttendanceRecord.student_id
            )
        ).scalars().all()
    )


def _record_for(session: Session, task_id: int, student_id: int) -> AttendanceRecord:
    return next(r for r in _records(session, task_id) if r.student_id == student_id)


def _versions(session: Session, record_id: int) -> list[AttendanceRecordVersion]:
    session.commit()
    session.expire_all()
    return list(
        session.execute(
            select(AttendanceRecordVersion)
            .where(AttendanceRecordVersion.attendance_record_id == record_id)
            .order_by(AttendanceRecordVersion.version_no)
        ).scalars().all()
    )


def _submission(session: Session, sub_id: int) -> InspectionSubmission:
    session.commit()
    session.expire_all()
    return session.get(InspectionSubmission, sub_id)  # type: ignore[return-value]


def _task(session: Session, task_id: int) -> InspectionTask:
    session.commit()
    session.expire_all()
    return session.get(InspectionTask, task_id)  # type: ignore[return-value]


def _audit_count(session: Session, action: str) -> int:
    session.commit()
    session.expire_all()
    return len(
        session.execute(select(AuditLog).where(AuditLog.action == action)).scalars().all()
    )


# --------------------------------------------------------------------------- #
# 审核守卫与鉴权
# --------------------------------------------------------------------------- #
def test_review_requires_auth_401(client: TestClient) -> None:
    assert client.post(_review_url(1), json={"decision": "APPROVED"}).status_code == 401


def test_volunteer_cannot_review_403(client: TestClient, session: Session) -> None:
    # 志愿者有 submission.create/read 却无 review → 路由守卫即 403。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _, vh = _make_volunteer(client, h, session, sc)
    r = client.post(_review_url(1), headers=vh, json={"decision": "APPROVED"})
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- #
# 通过生成考勤 + 五态完成 + 审计
# --------------------------------------------------------------------------- #
def test_approve_abnormal_generates_attendance(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc, abnormal=True)
    r = client.post(_review_url(sub_id), headers=h,
                    json={"decision": "APPROVED", "comment": "属实"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["review_status"] == ReviewStatus.APPROVED.value
    recs = _records(session, sc["task_id"])
    assert len(recs) == 2  # 名单两生各一条
    by_student = {rec.student_id: rec for rec in recs}
    assert by_student[sc["s1"]].effective_type == AttendanceType.LATE.value
    assert by_student[sc["s2"]].effective_type == AttendanceType.NORMAL.value
    assert by_student[sc["s1"]].source_submission_item_id is not None
    assert by_student[sc["s2"]].source_submission_item_id is None
    assert by_student[sc["s1"]].current_version == 1
    # 初始版本来源 SUBMISSION。
    v1 = _versions(session, by_student[sc["s1"]].id)[0]
    assert v1.version_no == 1
    assert v1.source_type == AttendanceSourceType.SUBMISSION.value
    assert v1.attendance_type == AttendanceType.LATE.value
    # 五态：有 APPROVED 提交 → 已完成。
    detail = client.get(f"{_TASKS}/{sc['task_id']}", headers=h).json()["data"]
    assert detail["status"] == "已完成"
    assert _audit_count(session, "submission.review.approved") == 1


def test_approve_normal_all_normal(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc, abnormal=False)
    r = client.post(_review_url(sub_id), headers=h, json={"decision": "APPROVED"})
    assert r.status_code == 200, r.text
    recs = _records(session, sc["task_id"])
    assert len(recs) == 2
    assert all(rec.effective_type == AttendanceType.NORMAL.value for rec in recs)
    assert all(rec.source_submission_item_id is None for rec in recs)


# --------------------------------------------------------------------------- #
# 驳回：保留事实、不生成考勤、可再生成下一 attempt
# --------------------------------------------------------------------------- #
def test_reject_preserves_and_allows_next_attempt(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc, abnormal=True)
    r = client.post(_review_url(sub_id), headers=h,
                    json={"decision": "REJECTED", "comment": "名单核对不实"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["review_status"] == ReviewStatus.REJECTED.value
    assert r.json()["data"]["review_comment"] == "名单核对不实"
    assert _records(session, sc["task_id"]) == []  # 驳回不生成考勤
    # 驳回后志愿者可再次提交 → attempt 2。
    vh = _bearer(_login(client, f"vol{sc['task_id']}abn"))
    r2 = client.post(_submit_url(sc["task_id"]), headers=vh, json=_normal_body())
    assert r2.status_code == 200, r2.text
    assert int(r2.json()["data"]["attempt_no"]) == 2
    assert _audit_count(session, "submission.review.rejected") == 1


# --------------------------------------------------------------------------- #
# 幂等 + 并发
# --------------------------------------------------------------------------- #
def test_review_twice_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc)
    assert client.post(_review_url(sub_id), headers=h,
                       json={"decision": "APPROVED"}).status_code == 200
    r = client.post(_review_url(sub_id), headers=h, json={"decision": "REJECTED"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.STATE_CONFLICT.value
    # 二次驳回被拒：仍只有审核通过那一版结果、考勤不翻倍。
    assert len(_records(session, sc["task_id"])) == 2


def _review_worker(
    engine, actor_id: int, sub_id: int, decision: str, barrier, out: dict, idx: int
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="admin", display_name="admin",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        from app.modules.inspection.schemas import SubmissionReviewRequest

        req = SubmissionReviewRequest(decision=decision, comment="c")  # type: ignore[arg-type]
        barrier.wait()
        InspectionService(s).review_submission(actor, sub_id, req, f"conc-{idx}")
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_concurrent_double_approve_one_attendance(
    client: TestClient, engine: Engine, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc)
    admin_id = session.execute(
        select(UserAccount.id).where(UserAccount.username == "admin")
    ).scalar_one()
    session.commit()
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(target=_review_worker,
                         args=(engine, admin_id, sub_id, "APPROVED", barrier, out, i))
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    oks = [k for k, v in out.items() if v[0] == "ok"]
    errs = [v for k, v in out.items() if v[0] == "error"]
    assert len(oks) == 1, out
    assert len(errs) == 1, out
    assert "ConflictError" in errs[0][1]
    # 考勤恰好一份（两生），未因并发翻倍。
    assert len(_records(session, sc["task_id"])) == 2


def _mixed_worker(
    engine, actor_id: int, task_id: int, sub_id: int, mode: str, barrier, out: dict, idx: int
) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        actor = CurrentUser(
            id=actor_id, username="admin", display_name="admin",
            status=UserStatus.ACTIVE.value, roles=[RoleCode.SUPER_ADMIN.value], permissions=[],
        )
        barrier.wait()
        if mode == "review":
            from app.modules.inspection.schemas import SubmissionReviewRequest

            InspectionService(s).review_submission(
                actor, sub_id, SubmissionReviewRequest(decision="APPROVED"), f"mx-{idx}"
            )
        else:
            from app.modules.inspection.schemas import TaskCancelRequest

            t = s.get(InspectionTask, task_id)
            assert t is not None
            InspectionService(s).cancel_task(
                actor, task_id, TaskCancelRequest(reason="并发取消", lock_version=t.lock_version),
                f"mx-{idx}",
            )
        out[idx] = ("ok",)
    except Exception as exc:  # noqa: BLE001
        s.rollback()
        out[idx] = ("error", repr(exc))
    finally:
        s.close()


def test_review_vs_cancel_mutually_exclusive(
    client: TestClient, engine: Engine, session: Session
) -> None:
    # 审核通过 vs 取消：都锁任务，恰一成功，状态互斥（不会既取消又生成考勤）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc)
    admin_id = session.execute(
        select(UserAccount.id).where(UserAccount.username == "admin")
    ).scalar_one()
    session.commit()
    session.expire_all()

    barrier: threading.Barrier = threading.Barrier(2)
    out: dict[int, object] = {}
    threads = [
        threading.Thread(target=_mixed_worker,
                         args=(engine, admin_id, sc["task_id"], sub_id, "review", barrier, out, 0)),
        threading.Thread(target=_mixed_worker,
                         args=(engine, admin_id, sc["task_id"], sub_id, "cancel", barrier, out, 1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    oks = [v for v in out.values() if v[0] == "ok"]
    errs = [v for v in out.values() if v[0] == "error"]
    assert len(oks) == 1, out
    assert len(errs) == 1, out
    assert "ConflictError" in errs[0][1]
    task = _task(session, sc["task_id"])
    recs = _records(session, sc["task_id"])
    # 互斥：要么取消且无考勤，要么通过且有考勤，绝不并存。
    assert (task.canceled_at is not None) != (len(recs) > 0), (task.canceled_at, len(recs))


# --------------------------------------------------------------------------- #
# 取消守卫（51）
# --------------------------------------------------------------------------- #
def test_cancel_after_approved_blocked_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc)
    assert client.post(_review_url(sub_id), headers=h,
                       json={"decision": "APPROVED"}).status_code == 200
    task = _task(session, sc["task_id"])
    r = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                    json={"reason": "误取消", "lock_version": task.lock_version})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.STATE_CONFLICT.value


def test_review_canceled_task_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    sub_id = _pending_submission(client, h, session, sc)
    task = _task(session, sc["task_id"])
    c = client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                    json={"reason": "停课", "lock_version": task.lock_version})
    assert c.status_code == 200, c.text
    r = client.post(_review_url(sub_id), headers=h, json={"decision": "APPROVED"})
    assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# 考勤读取范围
# --------------------------------------------------------------------------- #
def _approve_setup(client, h, session, sc) -> dict[int, int]:
    """提交 ABNORMAL + 审核通过，返回 {student_id: attendance_record_id}。"""
    sub_id = _pending_submission(client, h, session, sc, abnormal=True)
    assert client.post(_review_url(sub_id), headers=h,
                       json={"decision": "APPROVED"}).status_code == 200
    return {r.student_id: r.id for r in _records(session, sc["task_id"])}


def test_attendance_list_requires_manage_scope_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _approve_setup(client, h, session, sc)
    # STUDENT 有 attendance.read 但仅本人范围：GET /attendance（管理范围）应被 Service 拒 403。
    _make_user(session, "stu_s1", [RoleCode.STUDENT.value], student_id=sc["s1"])
    sh = _bearer(_login(client, "stu_s1"))
    r = client.get(_ATT, headers=sh)
    assert r.status_code == 403, r.text


def test_me_attendance_self_only(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _approve_setup(client, h, session, sc)
    # s1 绑定一名学生账号 → /me/attendance 仅本人 S001 的记录（LATE）。
    stu = _make_user(session, "stu_s1", [RoleCode.STUDENT.value], student_id=sc["s1"])
    _ = stu
    sh = _bearer(_login(client, "stu_s1"))
    data = client.get(_ME_ATT, headers=sh).json()["data"]
    assert data["total"] == 1
    assert int(data["items"][0]["student_id"]) == sc["s1"]
    assert data["items"][0]["effective_type"] == AttendanceType.LATE.value
    assert data["items"][0]["student_no"] == "S001"


def test_attendance_detail_scope_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    _make_user(session, "stu_s1", [RoleCode.STUDENT.value], student_id=sc["s1"])
    sh = _bearer(_login(client, "stu_s1"))
    # 本人记录可读，他人记录统一 404 防枚举。
    assert client.get(f"{_ATT}/{rec_ids[sc['s1']]}", headers=sh).status_code == 200
    assert client.get(f"{_ATT}/{rec_ids[sc['s2']]}", headers=sh).status_code == 404
    # 管理范围两者皆可读，且版本列表可见初始 SUBMISSION 版本。
    assert client.get(f"{_ATT}/{rec_ids[sc['s2']]}", headers=h).status_code == 200
    vers = client.get(f"{_ATT}/{rec_ids[sc['s1']]}/versions", headers=h).json()["data"]
    assert len(vers) == 1
    assert vers[0]["source_type"] == AttendanceSourceType.SUBMISSION.value


# --------------------------------------------------------------------------- #
# 更正：乐观锁 + 追加版本
# --------------------------------------------------------------------------- #
def _correct_url(record_id: int) -> str:
    return f"{_ATT}/{record_id}/corrections"


def test_correction_optimistic_lock_and_version(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    rid = rec_ids[sc["s2"]]  # 起初 NORMAL
    r = client.post(_correct_url(rid), headers=h,
                    json={"attendance_type": "ABSENT", "reason": "补录旷课", "current_version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["effective_type"] == AttendanceType.ABSENT.value
    assert int(r.json()["data"]["current_version"]) == 2
    rec = session.get(AttendanceRecord, rid)
    assert rec is not None
    vers = _versions(session, rid)
    assert [v.version_no for v in vers] == [1, 2]
    assert vers[1].source_type == AttendanceSourceType.CORRECTION.value
    assert vers[1].attendance_type == AttendanceType.ABSENT.value
    assert vers[1].reason == "补录旷课"
    # 陈旧版本再更正 → 409 VERSION_CONFLICT。
    r2 = client.post(_correct_url(rid), headers=h,
                     json={"attendance_type": "LATE", "reason": "旧版本", "current_version": 1})
    assert r2.status_code == 409, r2.text
    assert r2.json()["code"] == ErrorCode.VERSION_CONFLICT.value


def test_correction_requires_admin_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    rec_ids = _approve_setup(client, h, session, sc)
    _make_user(session, "stu_s1", [RoleCode.STUDENT.value], student_id=sc["s1"])
    sh = _bearer(_login(client, "stu_s1"))
    r = client.post(_correct_url(rec_ids[sc["s1"]]), headers=sh,
                    json={"attendance_type": "NORMAL", "reason": "越权", "current_version": 1})
    assert r.status_code == 403, r.text


def test_correction_missing_record_404(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    _bootstrap(session)
    r = client.post(_correct_url(999999), headers=h,
                    json={"attendance_type": "NORMAL", "reason": "无", "current_version": 1})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# 应到人数调整
# --------------------------------------------------------------------------- #
def _ec_url(task_id: int) -> str:
    return f"{_TASKS}/{task_id}/expected-count"


def test_expected_count_adjust_ok_keeps_snapshot(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    task = _task(session, sc["task_id"])
    snap = task.expected_count_snapshot
    r = client.patch(
        _ec_url(sc["task_id"]), headers=h,
        json={"expected_count_current": 30, "reason": "含旁听", "lock_version": task.lock_version},
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["data"]["expected_count_current"]) == 30
    after = _task(session, sc["task_id"])
    assert after.expected_count_snapshot == snap  # 初始快照不动
    assert after.expected_count_current == 30
    assert _audit_count(session, "attendance.expected_count_adjust") == 1


def test_expected_count_below_abnormal_422(client: TestClient, session: Session) -> None:
    # 审核通过后有 1 名异常（LATE），把应到人数压到 0 → 422（应到 < 异常）。
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _approve_setup(client, h, session, sc)
    task = _task(session, sc["task_id"])
    r = client.patch(
        _ec_url(sc["task_id"]), headers=h,
        json={"expected_count_current": 0, "reason": "过低", "lock_version": task.lock_version},
    )
    assert r.status_code == 422, r.text
    assert r.json()["fieldErrors"]["abnormal_count"] == 1


def test_expected_count_version_conflict_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _task(session, sc["task_id"])
    r = client.patch(_ec_url(sc["task_id"]), headers=h,
                     json={"expected_count_current": 10, "reason": "旧版本", "lock_version": 999})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == ErrorCode.VERSION_CONFLICT.value


def test_expected_count_negative_schema_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    task = _task(session, sc["task_id"])
    r = client.patch(
        _ec_url(sc["task_id"]), headers=h,
        json={"expected_count_current": -1, "reason": "负", "lock_version": task.lock_version},
    )
    assert r.status_code == 422, r.text


def test_expected_count_requires_perm_403(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _, vh = _make_volunteer(client, h, session, sc)
    r = client.patch(_ec_url(sc["task_id"]), headers=vh,
                     json={"expected_count_current": 10, "reason": "越权", "lock_version": 0})
    assert r.status_code == 403, r.text


def test_expected_count_canceled_task_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    task = _task(session, sc["task_id"])
    assert client.post(f"{_TASKS}/{sc['task_id']}/cancel", headers=h,
                       json={"reason": "停", "lock_version": task.lock_version}).status_code == 200
    after = _task(session, sc["task_id"])
    r = client.patch(
        _ec_url(sc["task_id"]), headers=h,
        json={"expected_count_current": 10, "reason": "取消后", "lock_version": after.lock_version},
    )
    assert r.status_code == 409, r.text
