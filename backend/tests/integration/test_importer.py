"""导入模块（P3 Wave 4：预览→确认两步整批原子）集成测试，连真实 MySQL 测试库。

覆盖 DEVELOPMENT_PLAN P3 与 PERMISSIONS.md 12.5：
- 认证/组合权限：无令牌 401；缺 import.execute 403（路由早拦）；有 execute 缺目标
  manage 403（服务事务内纵深复核）；模板仅需目标 manage。
- 目标/作用域校验：未知 target 422；缺作用域参数 422；作用域资源不存在 404。
- 名单：预览不落库、可确认；确认整体替换；未知学号→预览 error 不可确认；确认前学号
  被删→422 且名单零副作用（原子）；审计 preview/confirm 各一条。
- 课表：周次解析（1-16周/单双周）、确认建课/教学班/课表+周次；周次越界 422；
  结束早于开始 422（预览 error）。
- 志愿者资格：绑定学生确认即时补授 VOLUNTEER；未绑定仅落资格；停用不补授。
- "先导入资格后绑定"：先导入启用资格→后绑定微信→bind_student 反向补授 VOLUNTEER。
- 状态机：确认重复 409；预览过期 409（并置 EXPIRED）。
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from app.core.database import utcnow
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import hash_password, hash_token
from app.modules.academic.models import (
    CourseSchedule,
    CourseScheduleWeek,
    TeachingClass,
    VolunteerQualification,
)
from app.modules.audit.models import AuditLog
from app.modules.identity.models import (
    IdentityBindingToken,
    Permission,
    Role,
    UserAccount,
    UserStatus,
)
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import IdentityService
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

_PWD = "Passw0rd#1"
_IM = "/api/v1/imports"
_TP = "/api/v1/import-templates"

EXEC = PermissionCode.IMPORT_EXECUTE.value
STU_M = PermissionCode.STUDENT_MANAGE.value
ACA_M = PermissionCode.ACADEMIC_MANAGE.value
VOL_M = PermissionCode.VOLUNTEER_MANAGE.value


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
    """挂载一个仅含指定权限码的自定义角色，用于精确构造组合权限象限。"""
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


def _xlsx(headers: list[str], rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post_import(
    client: TestClient,
    headers: dict[str, str],
    *,
    target: str,
    content: bytes,
    semester_id: int | str | None = None,
    teaching_class_id: int | str | None = None,
    replace: bool = True,
):
    data: dict[str, str] = {"target": target, "replace": "true" if replace else "false"}
    if semester_id is not None:
        data["semester_id"] = str(semester_id)
    if teaching_class_id is not None:
        data["teaching_class_id"] = str(teaching_class_id)
    files = {
        "file": (
            "import.xlsx",
            io.BytesIO(content),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    return client.post(_IM, headers=headers, data=data, files=files)


def _scene(client: TestClient, headers: dict[str, str]) -> dict:
    """建 ACTIVE 学期(20 周) + 行政班 + 两名学生(S001,S002) + 课程 + 教学班。"""
    sem = client.post(
        "/api/v1/academic/semesters",
        headers=headers,
        json={
            "code": "2026FA",
            "name": "2026秋",
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
            "first_monday": "2026-09-07",
            "total_weeks": 20,
        },
    ).json()["data"]
    cls = client.post(
        "/api/v1/academic/administrative-classes",
        headers=headers,
        json={"class_code": "CS2401", "class_name": "计算机2401", "college": "计算机学院"},
    ).json()["data"]
    students = {}
    for no in ("S001", "S002"):
        students[no] = client.post(
            "/api/v1/academic/students",
            headers=headers,
            json={"student_no": no, "name": f"学生{no}", "administrative_class_id": int(cls["id"])},
        ).json()["data"]
    course = client.post(
        "/api/v1/academic/courses",
        headers=headers,
        json={"course_code": "C001", "course_name": "高等数学"},
    ).json()["data"]
    tc = client.post(
        "/api/v1/academic/teaching-classes",
        headers=headers,
        json={
            "semester_id": int(sem["id"]),
            "course_id": int(course["id"]),
            "class_code": "T1",
            "class_name": "教学班T1",
        },
    ).json()["data"]
    return {
        "semester_id": int(sem["id"]),
        "class_id": int(cls["id"]),
        "students": students,
        "course_id": int(course["id"]),
        "tc_id": int(tc["id"]),
    }


def _roster(client: TestClient, headers: dict[str, str], tc_id: int) -> list:
    data = client.get(
        f"/api/v1/academic/teaching-classes/{tc_id}/students", headers=headers
    ).json()["data"]
    return data["items"]


def _audit_actions(session: Session, action: str) -> int:
    return len(
        session.execute(
            select(AuditLog).where(AuditLog.action == action)
        ).scalars().all()
    )


# --------------------------------------------------------------------------- #
# 认证与组合权限
# --------------------------------------------------------------------------- #
def test_import_requires_auth_401(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    assert client.get(_TP + "/roster").status_code == 401
    resp = _post_import(client, {}, target="roster", content=_xlsx(["学号"], []))
    assert resp.status_code == 401


def test_missing_import_execute_forbidden_403(
    client: TestClient, session: Session
) -> None:
    # 仅有目标 manage（student.manage），缺 import.execute → 路由 ImportExecuteDep 403。
    _bootstrap(session)
    _make_perm_user(session, "manageonly", [STU_M])
    h = _bearer(_login(client, "manageonly"))
    resp = _post_import(client, h, target="roster", content=_xlsx(["学号"], []))
    assert resp.status_code == 403


def test_missing_target_manage_forbidden_403(
    client: TestClient, session: Session
) -> None:
    # 仅有 import.execute，缺目标 manage → 路由放行，服务事务内组合校验 403。
    _bootstrap(session)
    _make_perm_user(session, "exonly", [EXEC])
    h = _bearer(_login(client, "exonly"))
    resp = _post_import(client, h, target="roster", content=_xlsx(["学号"], []))
    assert resp.status_code == 403


def test_template_requires_target_manage(client: TestClient, session: Session) -> None:
    _bootstrap(session)
    _make_perm_user(session, "exonly", [EXEC])
    h = _bearer(_login(client, "exonly"))
    # 有 execute 无 student.manage → 下载 roster 模板 403。
    assert client.get(_TP + "/roster", headers=h).status_code == 403
    # 有 manage → 200。
    _make_perm_user(session, "stumanage", [STU_M])
    h2 = _bearer(_login(client, "stumanage"))
    r = client.get(_TP + "/roster", headers=h2)
    assert r.status_code == 200
    assert r.json()["data"]["target"] == "roster"


# --------------------------------------------------------------------------- #
# 目标与作用域校验
# --------------------------------------------------------------------------- #
def test_unknown_target_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    resp = _post_import(client, h, target="bogus", content=_xlsx(["学号"], []))
    assert resp.status_code == 422


def test_roster_missing_teaching_class_422(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    resp = _post_import(client, h, target="roster", content=_xlsx(["学号"], []))
    assert resp.status_code == 422


def test_roster_unknown_teaching_class_404(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    resp = _post_import(
        client, h, target="roster", content=_xlsx(["学号"], []), teaching_class_id=999999
    )
    assert resp.status_code == 404


def test_volunteer_missing_semester_scope(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    assert (
        _post_import(client, h, target="volunteer", content=_xlsx(["学号"], [])).status_code
        == 422
    )
    assert (
        _post_import(
            client, h, target="volunteer", content=_xlsx(["学号"], []), semester_id=999999
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# 名单：两步原子
# --------------------------------------------------------------------------- #
def test_roster_preview_confirm_two_step(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号", "姓名"], [{"学号": "S001", "姓名": "学生S001"}, {"学号": "S002"}])

    prev = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    )
    assert prev.status_code == 200, prev.text
    pdata = prev.json()["data"]
    assert pdata["status"] == "PREVIEW"
    assert pdata["can_confirm"] is True
    assert pdata["errors"] == []
    assert int(pdata["summary"]["student_total"]) == 2
    batch_id = int(pdata["id"])

    # 预览绝不写业务表：此刻名单为空。
    session.expire_all()
    assert _roster(client, h, sc["tc_id"]) == []

    conf = client.post(f"{_IM}/{batch_id}/confirm", headers=h)
    assert conf.status_code == 200, conf.text
    cdata = conf.json()["data"]
    assert cdata["status"] == "CONFIRMED"
    assert int(cdata["summary"]["roster_after"]) == 2

    # 确认后台名落库。
    roster_after = _roster(client, h, sc["tc_id"])
    assert {r["student_no"] for r in roster_after} == {"S001", "S002"}

    # 审计各一条。
    session.expire_all()
    assert _audit_actions(session, "import.batch.preview") >= 1
    assert _audit_actions(session, "import.batch.confirm") == 1


def test_roster_duplicate_confirm_409(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号"], [{"学号": "S001"}])
    pdata = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    ).json()["data"]
    batch_id = int(pdata["id"])
    assert client.post(f"{_IM}/{batch_id}/confirm", headers=h).status_code == 200
    again = client.post(f"{_IM}/{batch_id}/confirm", headers=h)
    assert again.status_code == 409


def test_roster_preview_error_blocks_confirm(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号"], [{"学号": "S001"}, {"学号": "GHOST"}])
    pdata = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    ).json()["data"]
    assert pdata["can_confirm"] is False
    assert any(e["code"] == "unknown_student" for e in pdata["errors"])
    assert int(pdata["summary"]["error_count"]) == 1
    conf = client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h)
    assert conf.status_code == 422


def test_roster_atomicity_reference_removed_before_confirm(
    client: TestClient, session: Session
) -> None:
    """预览时学号存在，确认前被删 → 422 且名单零副作用（原子无部分写入）。"""
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号"], [{"学号": "S001"}, {"学号": "S002"}])
    pdata = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    ).json()["data"]
    batch_id = int(pdata["id"])

    # 直接删除 S002（模拟外部引用在预览与确认之间失效）。
    from app.modules.academic.models import Student

    s2 = session.execute(select(Student).where(Student.student_no == "S002")).scalar_one()
    session.delete(s2)
    session.commit()

    conf = client.post(f"{_IM}/{batch_id}/confirm", headers=h)
    assert conf.status_code == 422

    # 原子性：确认失败后名单保持为空（未落任何部分行）。
    assert _roster(client, h, sc["tc_id"]) == []


def test_roster_replace_overwrites_existing(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 先导 S001。
    p1 = _post_import(
        client, h, target="roster", content=_xlsx(["学号"], [{"学号": "S001"}]),
        teaching_class_id=sc["tc_id"],
    ).json()["data"]
    client.post(f"{_IM}/{int(p1['id'])}/confirm", headers=h)
    # 再整体替换为 S002。
    p2 = _post_import(
        client, h, target="roster", content=_xlsx(["学号"], [{"学号": "S002"}]),
        teaching_class_id=sc["tc_id"],
    ).json()["data"]
    conf = client.post(f"{_IM}/{int(p2['id'])}/confirm", headers=h).json()["data"]
    assert int(conf["summary"]["roster_before"]) == 1
    roster = _roster(client, h, sc["tc_id"])
    assert {r["student_no"] for r in roster} == {"S002"}


# --------------------------------------------------------------------------- #
# 课表
# --------------------------------------------------------------------------- #
def test_timetable_preview_confirm_creates_graph(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    headers_row = [
        "教学班码", "课程代码", "课程名称", "星期", "开始大节", "结束大节", "周次", "上课地点"
    ]
    content = _xlsx(
        headers_row,
        [
            {
                "教学班码": "NEW-A", "课程代码": "CNEW", "课程名称": "线性代数",
                "星期": "周一", "开始大节": "1", "结束大节": "2", "周次": "1-16周",
                "上课地点": "A101",
            },
            {
                "教学班码": "NEW-A", "课程代码": "CNEW", "课程名称": "线性代数",
                "星期": "周三", "开始大节": "3", "结束大节": "4", "周次": "2-15双周",
                "上课地点": "A102",
            },
        ],
    )
    pdata = _post_import(
        client, h, target="timetable", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    assert pdata["can_confirm"] is True, pdata["errors"]
    assert int(pdata["summary"]["schedule_count"]) == 2

    conf = client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h)
    assert conf.status_code == 200, conf.text
    csum = conf.json()["data"]["summary"]
    assert int(csum["schedule_created"]) == 2
    assert int(csum["teaching_class_created"]) == 1
    assert int(csum["course_created"]) == 1

    # 周次落库校验：第一条 1..16，第二条 2..15 偶数。
    session.expire_all()
    scheds = session.execute(
        select(CourseSchedule).where(CourseSchedule.semester_id == sc["semester_id"])
    ).scalars().all()
    assert len(scheds) == 2
    weeks_map = {}
    for s in scheds:
        ws = session.execute(
            select(CourseScheduleWeek.week_no).where(CourseScheduleWeek.schedule_id == s.id)
        ).scalars().all()
        weeks_map[s.weekday] = list(ws)
    assert weeks_map[1] == list(range(1, 17))  # 周一
    assert weeks_map[3] == list(range(2, 16, 2))  # 周三双周


def test_timetable_weeks_out_of_range_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    headers_row = [
        "教学班码", "课程代码", "课程名称", "星期", "开始大节", "结束大节", "周次", "上课地点"
    ]
    content = _xlsx(
        headers_row,
        [
            {
                "教学班码": "X", "课程代码": "CX", "星期": "周一",
                "开始大节": "1", "结束大节": "2", "周次": "1-30周",
            }
        ],
    )
    pdata = _post_import(
        client, h, target="timetable", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    assert pdata["can_confirm"] is False
    assert any(e["code"] == "bad_time_field" for e in pdata["errors"])


def test_timetable_period_inverted_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    headers_row = [
        "教学班码", "课程代码", "星期", "开始大节", "结束大节", "周次"
    ]
    content = _xlsx(
        headers_row,
        [
            {
                "教学班码": "Y", "课程代码": "CY", "星期": "周二",
                "开始大节": "5", "结束大节": "3", "周次": "1-8周",
            }
        ],
    )
    pdata = _post_import(
        client, h, target="timetable", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    assert any(e["code"] == "period_inverted" for e in pdata["errors"])
    assert client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h).status_code == 422


# --------------------------------------------------------------------------- #
# 志愿者资格
# --------------------------------------------------------------------------- #
def test_volunteer_bound_student_grants_role(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 给 S001 建绑定账号。
    _make_bound_account(session, "s001user", int(sc["students"]["S001"]["id"]), [])
    content = _xlsx(
        ["学号", "是否启用"],
        [{"学号": "S001", "是否启用": "是"}],
    )
    pdata = _post_import(
        client, h, target="volunteer", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    conf = client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h)
    assert conf.status_code == 200, conf.text
    assert int(conf.json()["data"]["summary"]["volunteer_role_granted"]) == 1

    session.expire_all()
    acct = session.execute(
        select(UserAccount).where(UserAccount.username == "s001user")
    ).scalar_one()
    role_codes = {r.code for r in acct.roles}
    assert RoleCode.VOLUNTEER.value in role_codes
    vq = session.execute(
        select(VolunteerQualification).where(
            VolunteerQualification.student_id == int(sc["students"]["S001"]["id"])
        )
    ).scalar_one()
    assert vq.enabled is True


def test_volunteer_unbound_creates_qualification_only(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号", "是否启用"], [{"学号": "S002", "是否启用": "1"}])
    pdata = _post_import(
        client, h, target="volunteer", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    conf = client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h)
    assert conf.status_code == 200
    assert int(conf.json()["data"]["summary"]["volunteer_role_granted"]) == 0
    session.expire_all()
    assert session.execute(
        select(VolunteerQualification).where(
            VolunteerQualification.student_id == int(sc["students"]["S002"]["id"])
        )
    ).scalar_one() is not None


def test_volunteer_disable_does_not_grant(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    _make_bound_account(session, "s001user", int(sc["students"]["S001"]["id"]), [])
    content = _xlsx(["学号", "是否启用"], [{"学号": "S001", "是否启用": "否"}])
    pdata = _post_import(
        client, h, target="volunteer", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h)
    session.expire_all()
    acct = session.execute(
        select(UserAccount).where(UserAccount.username == "s001user")
    ).scalar_one()
    assert RoleCode.VOLUNTEER.value not in {r.code for r in acct.roles}


# --------------------------------------------------------------------------- #
# "先导入资格后绑定"反向补授
# --------------------------------------------------------------------------- #
def test_qualification_imported_before_binding_grants_on_bind(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 1) 先为未绑定的 S002 导入启用中的志愿者资格。
    content = _xlsx(["学号", "是否启用"], [{"学号": "S002", "是否启用": "是"}])
    pdata = _post_import(
        client, h, target="volunteer", content=content, semester_id=sc["semester_id"]
    ).json()["data"]
    assert client.post(f"{_IM}/{int(pdata['id'])}/confirm", headers=h).status_code == 200

    # 2) 建无角色未绑定账号 + 一次性绑定码。
    user = _make_user(session, "wx_late", [])
    code = "LATE-BIND-CODE-123"
    session.add(
        IdentityBindingToken(
            student_id=int(sc["students"]["S002"]["id"]),
            token_hash=hash_token(code),
            status="UNUSED",
            expires_at=utcnow() + timedelta(hours=1),
        )
    )
    session.commit()

    # 3) 绑定：bind_student 应反向补授 VOLUNTEER。
    IdentityService(session).bind_student(user.id, "S002", code)
    session.expire_all()
    acct = session.execute(
        select(UserAccount).where(UserAccount.id == user.id)
    ).scalar_one()
    role_codes = {r.code for r in acct.roles}
    assert RoleCode.STUDENT.value in role_codes
    assert RoleCode.VOLUNTEER.value in role_codes


# --------------------------------------------------------------------------- #
# 状态机：过期
# --------------------------------------------------------------------------- #
def test_preview_expired_confirm_409_and_marks_expired(
    client: TestClient, session: Session
) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    content = _xlsx(["学号"], [{"学号": "S001"}])
    pdata = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    ).json()["data"]
    batch_id = int(pdata["id"])

    # 直接把过期时间拨到过去。
    from app.modules.importer.models import ImportBatch

    b = session.get(ImportBatch, batch_id)
    b.expires_at = utcnow() - timedelta(minutes=1)
    session.commit()

    conf = client.post(f"{_IM}/{batch_id}/confirm", headers=h)
    assert conf.status_code == 409
    session.expire_all()
    b2 = session.get(ImportBatch, batch_id)
    assert b2.status == "EXPIRED"


def test_get_errors_splits_severity(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    # 一条未知学号(error) + 一条重复(warning)。
    content = _xlsx(["学号"], [{"学号": "S001"}, {"学号": "S001"}, {"学号": "GHOST"}])
    pdata = _post_import(
        client, h, target="roster", content=content, teaching_class_id=sc["tc_id"]
    ).json()["data"]
    errs = client.get(f"{_IM}/{int(pdata['id'])}/errors", headers=h).json()["data"]
    assert any(e["code"] == "unknown_student" for e in errs["errors"])
    assert any(e["code"] == "duplicate_student" for e in errs["warnings"])


def test_invalid_xlsx_rejected_422(client: TestClient, session: Session) -> None:
    h = _admin_headers(client, session)
    sc = _scene(client, h)
    resp = _post_import(
        client,
        h,
        target="roster",
        content=b"not-a-real-xlsx-file",
        teaching_class_id=sc["tc_id"],
    )
    assert resp.status_code == 422


def test_teaching_class_model_imported_symbols() -> None:
    # 触发对模型符号的静态引用，避免未用导入被误删（保持测试自说明）。
    assert TeachingClass.__tablename__ == "teaching_class"
