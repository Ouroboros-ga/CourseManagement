"""版本化周报 P7(W7c)：三阶段有界同步生成、独立发布、落后判定与下载，连真实 MySQL + 本地存储。

覆盖技术方案 18 与 PERMISSIONS.md 5/6.2/7：
- 鉴权与门禁：无令牌 401；无 report.generate 的账号生成 → 403；statistics.read 不隐式授予
  report.read（读/下载周报均需 report.read）；负责人默认可读、可生成。
- 版本递增不可覆盖：同 (学期,周,范围) 连续生成得 version_no 1→2，历史版本留存不原地改。
- 下载不新增版本：重复下载同一版本，版本集合不变。
- 落后判定：源数据修订号在生成后前进 → 最新版本 behind_source=true。
- 公式/模板版本：生成时固化 rule/template 版本；当前值调高后旧版 rule_outdated/template_outdated。
- 独立发布与产物：已发布版本可下载 Excel(zip)与明细 JSON；对应文件行为 REPORT_FILE 且未过期。
- 规模超限拒绝：命中任务数超单次上限 → 422，GENERATING 版本置 FAILED（占位版本号不复用）。
- 中断接管：停留在 GENERATING 且已超接管预算的版本可被后续生成复用同版本号接管并发布。
- 未发布不可下载：GENERATING 版本下载 → 409。
- 真实并发（threading.Barrier + 独立会话）：并发首次生成不产生重复版本号、版本终态收敛为
  PUBLISHED/FAILED（无悬挂 GENERATING）、至少一份成功发布。
"""

from __future__ import annotations

import json
import threading
from datetime import date as date_
from datetime import timedelta
from typing import Any

import pytest
from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.core.exceptions import AppError, ConflictError
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.modules.file.models import FileCategory, FileObject, FileStatus
from app.modules.file.storage import LocalStorage
from app.modules.identity.models import Role, UserAccount, UserStatus
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import CurrentUser
from app.modules.inspection.models import InspectionTask, SubmissionDeadlineDay
from app.modules.report.models import (
    Report,
    ReportSourceRevision,
    ReportVersion,
    ReportVersionStatus,
)
from app.modules.report.router import get_report_service
from app.modules.report.version_service import ReportService
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_GEN = "/api/v1/inspection-tasks/generate"
_TASKS = "/api/v1/inspection-tasks"
_ACA = "/api/v1/academic"
_SUBS = "/api/v1/submissions"
_GEN_VER = "/api/v1/reports/weekly/versions"
_MON1 = "2026-09-07"
_MON1_D = date_(2026, 9, 7)


# --------------------------------------------------------------------------- #
# 装配助手（与 test_report_statistics 同构，令本文件自包含）
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


def _admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    _bootstrap(session)
    _make_user(session, "admin", [RoleCode.SUPER_ADMIN.value])
    return _bearer(_login(client, "admin"))


def _grant_optional(client: TestClient, h: dict[str, str], user: UserAccount, code: str) -> None:
    _put(
        client,
        h,
        f"/api/v1/users/{user.id}/optional-permissions/{code}",
        {"enabled": True, "lockVersion": user.lock_version, "reason": "兼看周报"},
    )


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
        f"{_ACA}/teaching-classes/{tc_id}/students", headers=h, json={"student_ids": sids}
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
        json={"semester_id": sem_id, "student_id": student_id, "enabled": True, "reason": "合格"},
    )
    assert rp.status_code == 200, rp.text


def _task_lock_version(session: Session, task_id: int) -> int:
    session.commit()
    session.expire_all()
    row = session.get(InspectionTask, task_id)
    assert row is not None
    return int(row.lock_version)


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


def _scene(client: TestClient, h: dict[str, str], session: Session) -> dict:
    """一学期 + 一行政班(s1,s2) + 教学班 T1(week1) + 审核通过的一异常（1 个符合条件任务）。"""
    sem_id = _setup_sem(client, h)
    cs = _create_admin_class(client, h, "CS2401")
    s1 = _create_student(client, h, "S001", cs)
    s2 = _create_student(client, h, "S002", cs)
    course = _create_course(client, h, "C001")
    t1 = _create_tc(client, h, sem_id, course, "T1")
    _enroll(client, h, t1, [s1, s2])
    _schedule(client, h, t1, 1, 2, "A101", 1)
    assert _gen_course(client, h, sem_id, [t1], [1]) == 1
    tasks = _list_tasks(client, h, sem_id)
    task_w1 = next(int(t["id"]) for t in tasks if int(t["week_no"]) == 1)
    return {"sem_id": sem_id, "s1": s1, "s2": s2, "task_w1": task_w1}


def _generate(client: TestClient, h: dict[str, str], sem_id: int, week_no: int = 1) -> dict:
    return _post(client, h, _GEN_VER, {"semester_id": sem_id, "week_no": week_no})


def _list_versions(client: TestClient, h: dict[str, str], report_id: int) -> dict:
    resp = client.get(f"/api/v1/reports/{report_id}/versions", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.fixture
def report_storage(tmp_path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    """把 ReportService 的存储后端换成临时目录本地存储（经依赖覆盖，测试结束自动还原）。"""
    from app.main import app

    storage = LocalStorage(str(tmp_path / "report_files"), "test-secret")

    def _factory(db: Session = Depends(get_db)) -> ReportService:
        return ReportService(db, storage=storage)

    monkeypatch.setitem(app.dependency_overrides, get_report_service, _factory)
    return storage


# --------------------------------------------------------------------------- #
# 鉴权 / 门禁
# --------------------------------------------------------------------------- #
def test_generate_requires_auth_401(client: TestClient) -> None:
    r = client.post(_GEN_VER, json={"semester_id": 1, "week_no": 1})
    assert r.status_code == 401, r.text


def test_generate_forbidden_without_generate_permission(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _make_user(session, "sam", [RoleCode.STUDENT.value])
    sam_h = _bearer(_login(client, "sam"))
    r = client.post(_GEN_VER, headers=sam_h, json={"semester_id": sc["sem_id"], "week_no": 1})
    assert r.status_code == 403, r.text


def test_statistics_optional_toggle_preserves_default_report_read(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    rid = int(_generate(client, h, sc["sem_id"])["report_id"])
    sam = _make_user(session, "sam2", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    _grant_optional(client, h, sam, "statistics.read")
    sam_h = _bearer(_login(client, "sam2"))
    assert client.get(f"/api/v1/reports/{rid}/versions", headers=sam_h).status_code == 200
    vid = int(_list_versions(client, h, rid)["items"][0]["id"])
    assert (
        client.get(
            f"/api/v1/report-versions/{vid}/download", headers=sam_h, params={"kind": "EXCEL"}
        ).status_code
        == 200
    )


def test_student_affairs_manager_can_read_and_generate(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    rid = int(_generate(client, h, sc["sem_id"])["report_id"])
    _make_user(session, "sam3", [RoleCode.STUDENT_AFFAIRS_MANAGER.value])
    sam_h = _bearer(_login(client, "sam3"))
    # 可读：版本列表 200
    assert client.get(f"/api/v1/reports/{rid}/versions", headers=sam_h).status_code == 200
    # 负责人默认同时具有 report.read 和 report.generate。
    assert (
        client.post(
            _GEN_VER, headers=sam_h, json={"semester_id": sc["sem_id"], "week_no": 1}
        ).status_code
        == 200
    )


# --------------------------------------------------------------------------- #
# 生成 → 版本列表 → 下载（Happy Path）
# --------------------------------------------------------------------------- #
def test_generate_list_and_download(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _generate(client, h, sc["sem_id"])
    assert data["scope"] == "COLLEGE"
    ver = data["version"]
    assert ver["version_no"] == 1
    assert ver["status"] == "PUBLISHED"
    assert ver["excel_available"] is True
    assert ver["snapshot_available"] is True
    assert ver["behind_source"] is False
    rid = int(data["report_id"])
    vid = int(ver["id"])

    listing = _list_versions(client, h, rid)
    assert listing["latest_version_no"] == 1
    assert len(listing["items"]) == 1
    assert listing["items"][0]["status"] == "PUBLISHED"

    # Excel：zip 魔术数 + 附件头
    x = client.get(f"/api/v1/report-versions/{vid}/download", headers=h, params={"kind": "EXCEL"})
    assert x.status_code == 200, x.text
    assert x.content.startswith(b"PK")
    assert "attachment" in x.headers["content-disposition"]
    assert "xlsx" in x.headers["content-disposition"]

    # 明细 JSON：可解析并含与统计一致的聚合口径
    j = client.get(
        f"/api/v1/report-versions/{vid}/download", headers=h, params={"kind": "SNAPSHOT"}
    )
    assert j.status_code == 200, j.text
    payload = json.loads(j.content.decode("utf-8"))
    assert payload["overall"]["expected_count"] == 2
    assert payload["overall"]["abnormal_count"] == 1
    assert payload["meta"]["scope"] == "COLLEGE"


# --------------------------------------------------------------------------- #
# 版本递增不可覆盖 + 下载不新增版本
# --------------------------------------------------------------------------- #
def test_version_increments_without_overwrite(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    first = _generate(client, h, sc["sem_id"])
    rid = int(first["report_id"])
    v1 = int(first["version"]["id"])
    second = _generate(client, h, sc["sem_id"])
    assert int(second["report_id"]) == rid  # 同一逻辑周报
    assert second["version"]["version_no"] == 2

    listing = _list_versions(client, h, rid)
    assert listing["latest_version_no"] == 2
    assert {int(it["version_no"]) for it in listing["items"]} == {1, 2}

    # 重复下载 v1 不新增版本
    for _ in range(2):
        client.get(f"/api/v1/report-versions/{v1}/download", headers=h, params={"kind": "EXCEL"})
    assert len(_list_versions(client, h, rid)["items"]) == 2


# --------------------------------------------------------------------------- #
# 落后判定：生成后源数据修订号前进
# --------------------------------------------------------------------------- #
def test_behind_source_after_revision_bump(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _generate(client, h, sc["sem_id"])
    rid = int(data["report_id"])
    assert data["version"]["behind_source"] is False

    # 模拟源数据被改动：把该 (学期,周) 的修订号抬高。审核通过写考勤时已同事务建了修订行，
    # 故优先 UPDATE（直达已提交行，不受本夹具会话旧快照影响），无行才 INSERT。
    rc = session.execute(
        update(ReportSourceRevision)
        .where(
            ReportSourceRevision.semester_id == sc["sem_id"],
            ReportSourceRevision.week_no == 1,
        )
        .values(revision=999)
    ).rowcount
    if not rc:
        session.add(ReportSourceRevision(semester_id=sc["sem_id"], week_no=1, revision=999))
    session.commit()
    session.expire_all()

    listing = _list_versions(client, h, rid)
    assert listing["current_source_revision"] == 999
    assert listing["latest_behind_source"] is True
    assert listing["items"][0]["behind_source"] is True


# --------------------------------------------------------------------------- #
# 公式/模板版本固化与"已更新"提示
# --------------------------------------------------------------------------- #
def test_rule_and_template_versions_recorded_and_outdated(
    client: TestClient,
    session: Session,
    report_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPORT_RULE_VERSION", "3")
    monkeypatch.setenv("REPORT_TEMPLATE_VERSION", "7")
    get_settings.cache_clear()
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _generate(client, h, sc["sem_id"])
    rid = int(data["report_id"])
    assert data["version"]["rule_version"] == 3
    assert data["version"]["template_version"] == 7
    listing = _list_versions(client, h, rid)
    assert listing["current_rule_version"] == 3
    assert listing["items"][0]["rule_outdated"] is False

    # 部署侧调高公式版本 → 旧版本 rule_outdated=true（历史版本不被原地改）。
    monkeypatch.setenv("REPORT_RULE_VERSION", "9")
    get_settings.cache_clear()
    after = _list_versions(client, h, rid)
    assert after["current_rule_version"] == 9
    assert after["items"][0]["rule_version"] == 3  # 仍固化在 3
    assert after["items"][0]["rule_outdated"] is True


# --------------------------------------------------------------------------- #
# 规模超限拒绝 → GENERATING 置 FAILED，占位版本号不复用
# --------------------------------------------------------------------------- #
def test_scale_limit_marks_failed_and_version_no_not_reused(
    client: TestClient,
    session: Session,
    report_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    monkeypatch.setenv("REPORT_GENERATE_MAX_TASKS", "0")
    get_settings.cache_clear()
    r = client.post(_GEN_VER, headers=h, json={"semester_id": sc["sem_id"], "week_no": 1})
    assert r.status_code == 422, r.text

    # 放宽上限后再生成：应得 version_no=2（FAILED 的 1 号占位不复用）。
    monkeypatch.setenv("REPORT_GENERATE_MAX_TASKS", "5000")
    get_settings.cache_clear()
    data = _generate(client, h, sc["sem_id"])
    rid = int(data["report_id"])
    assert data["version"]["version_no"] == 2
    items = _list_versions(client, h, rid)["items"]
    by_no = {int(it["version_no"]): it for it in items}
    assert by_no[1]["status"] == "FAILED"
    assert by_no[1]["excel_available"] is False
    assert by_no[2]["status"] == "PUBLISHED"


def test_second_artifact_save_failure_marks_failed_and_removes_first(
    client: TestClient,
    session: Session,
    report_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _admin_headers(client, session)
    sem_id = _setup_sem(client, h)
    saved_keys: list[str] = []
    original_save = report_storage.save

    def fail_second_save(key: str, data: bytes, content_type: str) -> None:
        if saved_keys:
            raise RuntimeError("second artifact storage failed")
        original_save(key, data, content_type)
        saved_keys.append(key)

    monkeypatch.setattr(report_storage, "save", fail_second_save)
    with pytest.raises(RuntimeError, match="second artifact storage failed"):
        client.post(_GEN_VER, headers=h, json={"semester_id": sem_id, "week_no": 1})

    session.rollback()
    session.expire_all()
    report = session.execute(
        select(Report).where(Report.semester_id == sem_id, Report.week_no == 1)
    ).scalar_one()
    versions = (
        session.execute(select(ReportVersion).where(ReportVersion.report_id == report.id))
        .scalars()
        .all()
    )
    assert len(versions) == 1
    assert versions[0].status == ReportVersionStatus.FAILED.value
    assert versions[0].snapshot_file_id is None
    assert versions[0].excel_file_id is None
    assert len(saved_keys) == 1
    assert report_storage.exists(saved_keys[0]) is False


# --------------------------------------------------------------------------- #
# 独立发布：文件行为 REPORT_FILE 且未过期
# --------------------------------------------------------------------------- #
def test_generated_files_are_report_category_and_future(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    data = _generate(client, h, sc["sem_id"])
    rid = int(data["report_id"])
    session.commit()  # 结束旧快照，重开事务以看到应用连接已提交的版本/文件行
    session.expire_all()
    row = session.execute(
        select(ReportVersion).where(
            ReportVersion.report_id == rid,
            ReportVersion.status == ReportVersionStatus.PUBLISHED.value,
        )
    ).scalar_one()
    file_ids = [row.snapshot_file_id, row.excel_file_id]
    assert all(fid is not None for fid in file_ids)
    files = (
        session.execute(select(FileObject).where(FileObject.id.in_([int(f) for f in file_ids])))
        .scalars()
        .all()
    )
    now = utcnow()
    for f in files:
        assert f.category == FileCategory.REPORT_FILE.value
        assert f.status == FileStatus.READY.value
        assert f.uploader_user_id is None  # 服务端生成件无上传者
        assert f.expires_at is not None and f.expires_at > now  # 独立保留期未到期


# --------------------------------------------------------------------------- #
# 未发布不可下载 → 409
# --------------------------------------------------------------------------- #
def test_download_unpublished_version_409(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sem_id = _setup_sem(client, h)
    rep = Report(semester_id=sem_id, week_no=1, scope="COLLEGE", latest_version_no=1)
    session.add(rep)
    session.flush()
    gv = ReportVersion(
        report_id=rep.id,
        version_no=1,
        status=ReportVersionStatus.GENERATING.value,
        attempt_token="tok",
    )
    session.add(gv)
    session.commit()
    vid = gv.id
    r = client.get(f"/api/v1/report-versions/{vid}/download", headers=h, params={"kind": "EXCEL"})
    assert r.status_code == 409, r.text


# --------------------------------------------------------------------------- #
# 中断接管：超预算的 GENERATING 版本被复用同版本号发布
# --------------------------------------------------------------------------- #
def test_takeover_stale_generating_reuses_version_no(
    client: TestClient, session: Session, report_storage: LocalStorage
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    rep = Report(semester_id=sc["sem_id"], week_no=1, scope="COLLEGE", latest_version_no=1)
    session.add(rep)
    session.flush()
    stale = ReportVersion(
        report_id=rep.id,
        version_no=1,
        status=ReportVersionStatus.GENERATING.value,
        attempt_token="old-token",
    )
    session.add(stale)
    session.commit()
    stale_id = stale.id
    # 回拨创建时刻到接管预算之外，令其可被接管。
    session.execute(
        update(ReportVersion)
        .where(ReportVersion.id == stale_id)
        .values(created_at=utcnow() - timedelta(days=1))
    )
    session.commit()
    session.expire_all()

    data = _generate(client, h, sc["sem_id"])
    assert int(data["report_id"]) == rep.id
    assert data["version"]["version_no"] == 1  # 接管复用同版本号
    assert data["version"]["status"] == "PUBLISHED"
    items = _list_versions(client, h, rep.id)["items"]
    assert len(items) == 1  # 未新增版本行


# --------------------------------------------------------------------------- #
# 真实并发：不产生重复版本号、终态收敛、至少一份发布
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("same_actor", [False, True], ids=["different-actors", "same-actor"])
def test_concurrent_generation_no_duplicate_versions(
    client: TestClient, engine: Engine, session: Session, tmp_path, same_actor: bool
) -> None:
    # 用 HTTP 侧管理员夹具建数据 + 两个管理员账号，随后以独立会话并发调用服务。
    h = _admin_headers(client, session)
    sc = _scene(client, h, session)
    _approve_abnormal(
        client,
        h,
        session,
        sc["sem_id"],
        sc["task_w1"],
        [{"student_id": sc["s1"], "attendance_type": "LATE", "note": "迟到"}],
    )
    admin_b = _make_user(session, "adminB", [RoleCode.SUPER_ADMIN.value])
    admin_a_id = session.execute(
        select(UserAccount.id).where(UserAccount.username == "admin")
    ).scalar_one()

    storage = LocalStorage(str(tmp_path / "conc"), "test-secret")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _actor(user_id: int) -> CurrentUser:
        return CurrentUser(
            id=user_id,
            username=f"u{user_id}",
            display_name="x",
            status=UserStatus.ACTIVE.value,
            roles=[RoleCode.SUPER_ADMIN.value],
            permissions=[],
        )

    def _worker(user_id: int) -> None:
        with factory() as s:
            svc = ReportService(s, storage=storage)
            barrier.wait()
            try:
                svc.generate_version(
                    _actor(user_id),
                    semester_id=sc["sem_id"],
                    week_no=1,
                    scope="COLLEGE",
                    reason=None,
                    request_id=None,
                )
                with lock:
                    outcomes.append("ok")
            except (ConflictError, AppError):
                with lock:
                    outcomes.append("conflict")
            except Exception as exc:
                try:
                    s.rollback()
                except Exception as rollback_exc:
                    with lock:
                        errors.append(f"rollback after {exc!r}: {rollback_exc!r}")
                with lock:
                    outcomes.append("error")
                    errors.append(repr(exc))

    threads = [
        threading.Thread(target=_worker, args=(admin_a_id,), daemon=True),
        threading.Thread(
            target=_worker,
            args=(admin_a_id if same_actor else admin_b.id,),
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "并发生成线程未在 30 秒内结束"
    assert len(outcomes) == 2, f"两个并发调用未全部返回：{outcomes}, errors={errors}"
    assert not errors, f"并发生成出现未预期异常：{errors}"

    # 断言：版本号唯一（DB 唯一键兜底）、无悬挂 GENERATING、至少一份发布。
    session.commit()  # 结束旧快照，重开事务以看到工作线程会话已提交的版本行
    session.expire_all()
    report = session.execute(
        select(Report).where(Report.semester_id == sc["sem_id"], Report.week_no == 1)
    ).scalar_one()
    rows = (
        session.execute(select(ReportVersion).where(ReportVersion.report_id == report.id))
        .scalars()
        .all()
    )
    version_nos = [r.version_no for r in rows]
    assert len(version_nos) == len(set(version_nos))
    assert all(r.status != ReportVersionStatus.GENERATING.value for r in rows)
    published = [r for r in rows if r.status == ReportVersionStatus.PUBLISHED.value]
    assert len(published) >= 1
    assert "ok" in outcomes
