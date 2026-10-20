"""临时工号初始化只在明确核对后授予逐来源任职，不按姓名合并账号。"""

import copy

import pytest
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.academic.models import AdministrativeClass, TeachingClass
from app.modules.academic.staff_models import FacultyStaff, TeachingStaffAssignment
from app.modules.identity.models import UserAccount
from app.modules.identity.staff_binding import StaffBindingService
from sqlalchemy import func, select

from tests.unit.test_import_person_links import prepare
from tests.unit.test_staff_importer import configured, setup_env  # noqa: F401


def onboarding(campus):
    from app.modules.importer.staff_onboarding import StaffOnboarding

    service, db, actor, cid, other, sid = setup_env(campus)
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == cid))
    tc.teacher_name = "张老师、李老师"
    ac = db.scalar(select(AdministrativeClass).where(AdministrativeClass.college_id == cid))
    ac.head_teacher = "张老师"
    db.commit()
    return StaffOnboarding(service), db, actor, cid, other, sid


def decisions(plan):
    return [
        {
            "key": row["key"],
            "action": "CREATE",
            "person_key": row["name"],
            "home_college_id": plan["college_id"],
        }
        for row in plan["candidates"]
    ]


def test_preview_is_read_only_and_preserves_each_source(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    count = db.scalar(select(func.count()).select_from(UserAccount))
    plan = tool.preview(sid)
    assert {r["name"] for r in plan["candidates"]} == {"张老师", "李老师"}
    assert {r["kind"] for r in plan["candidates"]} == {"teaching", "responsibility"}
    assert db.scalar(select(FacultyStaff)) is None
    assert db.scalar(select(func.count()).select_from(UserAccount)) == count


def test_confirm_groups_only_explicit_person_keys_and_replays_without_duplicates(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    assert len(result["staff"]) == 2
    assert result["person_links_created"] == 3
    assert all(
        r.staff_no.startswith("TMP_") and r.temporary_staff_no == r.staff_no and r.user_id is None
        for r in db.scalars(select(FacultyStaff))
    )
    assert tool.confirm(plan, decisions(plan)) == result
    assert len(db.scalars(select(FacultyStaff)).all()) == 2
    assert len(db.scalars(select(TeachingStaffAssignment)).all()) == 2


def test_missing_decision_and_stale_source_cannot_write(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    with pytest.raises(ConflictError):
        tool.confirm(plan, [])
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == tool.service.cid))
    tc.teacher_name = "来源已变"
    db.commit()
    with pytest.raises(ConflictError):
        tool.confirm(plan, decisions(plan))
    assert db.scalar(select(FacultyStaff)) is None


def test_same_name_can_be_explicitly_split_but_is_never_implicitly_linked(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    reviewed = decisions(plan)
    for row in reviewed:
        row["person_key"] = row["key"]
    result = tool.confirm(plan, reviewed)
    assert len(result["staff"]) == 3
    assert len(db.scalars(select(FacultyStaff).where(FacultyStaff.name == "张老师")).all()) == 2


def test_existing_staff_requires_explicit_id_and_conflict_rolls_back_new_profiles(campus):
    from app.modules.importer.staff_onboarding import StaffOnboarding

    service, db, _, cid, _, sid, existing = prepare(campus)
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == cid))
    tc.teacher_name = existing.name
    db.commit()
    tool = StaffOnboarding(service)
    plan = tool.preview(sid)
    with pytest.raises(ConflictError):
        tool.confirm(plan, decisions(plan))
    reviewed = [
        {"key": r["key"], "action": "LINK", "staff_id": str(existing.id)}
        for r in plan["candidates"]
    ]
    result = tool.confirm(plan, reviewed)
    assert len(result["staff"]) == 1
    assert result["staff"][0]["staff_id"] == str(existing.id)


def test_plan_tampering_is_rejected(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    altered = copy.deepcopy(plan)
    altered["candidates"][0]["name"] = "伪造姓名"
    with pytest.raises(ConflictError):
        tool.confirm(altered, decisions(altered))
    assert db.scalar(select(FacultyStaff)) is None


def test_real_number_preserves_profile_and_old_number_still_redeems(campus):
    tool, db, actor, cid, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    row = db.get(FacultyStaff, int(result["staff"][0]["staff_id"]))
    old = row.staff_no
    tool.set_real_number(row.id, "000123", row.lock_version)
    assert row.staff_no == "000123" and row.temporary_staff_no == old
    token_id, code, _ = StaffBindingService(db, college_id=cid).issue_token(
        actor=actor, staff_id=row.id
    )
    account = UserAccount(display_name="微信测试教师", status="ACTIVE")
    db.add(account)
    db.commit()
    bound = StaffBindingService(db).redeem(user_id=account.id, staff_no=old, binding_code=code)
    assert bound["staff_id"] == str(row.id)
    assert token_id


def test_no_permission_cannot_preview_or_replay(campus):
    from app.modules.identity.service import CurrentUser
    from app.modules.importer.scoped_service import ScopedImporterService
    from app.modules.importer.staff_onboarding import StaffOnboarding

    tool, db, _, cid, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    account = UserAccount(display_name="无授权", status="ACTIVE")
    db.add(account)
    db.commit()
    actor = CurrentUser(account.id, None, "无授权", "ACTIVE", [], [])
    forbidden = StaffOnboarding(ScopedImporterService(db, actor, cid))
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        forbidden.preview(sid)
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        forbidden.confirm(plan, decisions(plan))
    assert result["staff"]


def test_binding_export_writes_exclusive_file_and_never_stores_plaintext(campus, tmp_path):
    from app.cli.staff_onboarding import export_credentials
    from app.core.security import hash_token
    from app.modules.identity.staff_binding_models import StaffBindingToken

    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    destination = tmp_path / "credentials.csv"
    export_credentials(tool, [int(r["staff_id"]) for r in result["staff"]], destination)
    import csv

    with destination.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 2
    token = db.scalar(select(StaffBindingToken))
    assert token.token_hash in {hash_token(r["绑定码"]) for r in rows}
    assert all(r["绑定码"] != token.token_hash for r in rows)
    count = len(db.scalars(select(StaffBindingToken)).all())
    with pytest.raises(FileExistsError):
        export_credentials(tool, [int(result["staff"][0]["staff_id"])], destination)
    assert len(db.scalars(select(StaffBindingToken)).all()) == count


def test_same_name_group_with_different_people_rolls_back(campus):
    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    reviewed = decisions(plan)
    for row in reviewed:
        row["person_key"] = "不能把所有教师当一个人"
    with pytest.raises(ConflictError):
        tool.confirm(plan, reviewed)
    assert db.scalar(select(FacultyStaff)) is None


def test_export_failure_rolls_back_binding_codes(campus, tmp_path, monkeypatch):
    from app.cli.staff_onboarding import export_credentials
    from app.modules.identity.staff_binding_models import StaffBindingToken

    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    destination = tmp_path / "failed.csv"

    def fail_commit():
        raise OSError("模拟数据库提交失败")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(OSError):
        export_credentials(tool, [int(result["staff"][0]["staff_id"])], destination)
    assert not destination.exists()
    assert db.scalar(select(StaffBindingToken)) is None


def test_responsibility_file_with_explicit_review_creates_missing_staff(campus):
    tool, db, _, _, _, _ = onboarding(campus)
    extra = {"class_duties": [{"class_name": "A1", "counselor": "新辅导员"}]}
    # 班级代码从实际 fixture 读取，避免依赖展示名称。
    ac = db.scalar(
        select(AdministrativeClass).where(AdministrativeClass.college_id == tool.service.cid)
    )
    extra["class_duties"][0]["class_name"] = ac.class_code
    plan = tool.preview(None, extra)
    assert "新辅导员" in {r["name"] for r in plan["candidates"]}
    result = tool.confirm(plan, decisions(plan), extra)
    assert result["person_links_created"] == 2


def test_create_requires_explicit_home_college(campus):
    tool, db, _, _, other, sid = onboarding(campus)
    plan = tool.preview(sid)
    review = decisions(plan)
    review[0]["home_college_id"] = str(other)
    with pytest.raises(ConflictError):
        tool.confirm(plan, review)
    assert db.scalar(select(FacultyStaff)) is None


def test_temporary_staff_cannot_use_web_password_login_until_real_number_is_confirmed(campus):
    from app.core.exceptions import UnauthenticatedError
    from app.core.security import hash_password
    from app.modules.identity.service import IdentityService

    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    staff = db.get(FacultyStaff, int(result["staff"][0]["staff_id"]))
    account = UserAccount(
        username="fixture-staff",
        display_name="教师",
        password_hash=hash_password("fixture-password"),
        status="ACTIVE",
    )
    db.add(account)
    db.flush()
    staff.user_id = account.id
    db.commit()
    with pytest.raises(UnauthenticatedError):
        IdentityService(db).login_web("fixture-staff", "fixture-password")
    tool.set_real_number(staff.id, "000567", staff.lock_version)
    pair = IdentityService(db).login_web("fixture-staff", "fixture-password")
    assert pair.access_token


def test_responsibility_file_parser_preserves_class_and_name(campus, tmp_path):
    from app.cli.staff_onboarding import responsibility_source

    from tests.unit.test_staff_importer import sheet

    tool, _, _, _, _, _ = onboarding(campus)
    path = tmp_path / "责任区.xlsx"
    path.write_bytes(sheet([["行政班", "班主任", "辅导员"], ["一班", "张老师", "新辅导员"]]))
    payload = responsibility_source(tool.service, path)
    assert payload["class_duties"][0]["counselor"] == "新辅导员"


def test_responsibility_source_accepts_original_header_and_preserves_explicit_numbers(
    campus, tmp_path
):
    from app.cli.staff_onboarding import responsibility_source

    from tests.unit.test_staff_importer import sheet

    tool, _, _, _, _, _ = onboarding(campus)
    path = tmp_path / "责任区.xlsx"
    path.write_bytes(
        sheet(
            [
                ["责任区名单"],
                [],
                ["班级代码", "班主任", "班主任工号", "辅导员"],
                ["C001", "张老师", "000123", "新辅导员"],
            ]
        )
    )
    payload = responsibility_source(tool.service, path)
    row = payload["class_duties"][0]
    assert row["class_name"] == "C001"
    assert row["head_teacher_staff_no"] == "000123"
    assert row["source_row"] == 4


def test_existing_same_name_can_be_explicitly_confirmed_as_a_different_person(campus):
    from app.modules.importer.staff_onboarding import StaffOnboarding

    service, db, _, cid, _, sid, existing = prepare(campus)
    tc = db.scalar(select(TeachingClass).where(TeachingClass.college_id == cid))
    tc.teacher_name = existing.name
    db.commit()
    tool = StaffOnboarding(service)
    plan = tool.preview(sid)
    review = decisions(plan)
    for row in review:
        row["distinct_from_staff_ids"] = [str(existing.id)]
    result = tool.confirm(plan, review)
    assert len(result["staff"]) == 1
    assert result["staff"][0]["staff_id"] != str(existing.id)


def test_cross_college_responsibility_conflict_rolls_back(campus):
    from app.modules.academic.staff_models import ClassStaffResponsibility

    tool, db, _, cid, other, sid = onboarding(campus)
    school_id = db.scalar(select(FacultyStaff.school_id))
    if school_id is None:
        from app.modules.organization.models import College

        school_id = db.get(College, cid).school_id
    foreign = FacultyStaff(
        school_id=school_id, college_id=other, staff_no="B001", name="张老师", status="ACTIVE"
    )
    db.add(foreign)
    db.commit()
    plan = tool.preview(sid)
    review = decisions(plan)
    for row in review:
        source = next(r for r in plan["candidates"] if r["key"] == row["key"])
        if source["name"] == foreign.name:
            row.update(action="LINK", staff_id=str(foreign.id))
    with pytest.raises(ConflictError):
        tool.confirm(plan, review)
    assert len(db.scalars(select(FacultyStaff)).all()) == 1
    assert db.scalar(select(ClassStaffResponsibility)) is None


def test_existing_web_session_and_refresh_are_blocked_after_linking_temporary_staff(campus):
    from app.core.exceptions import UnauthenticatedError
    from app.core.security import hash_password, hash_token
    from app.modules.identity.models import AuthSession
    from app.modules.identity.service import IdentityService

    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    staff = db.get(FacultyStaff, int(result["staff"][0]["staff_id"]))
    account = UserAccount(
        username="preexisting-web",
        display_name="教师",
        password_hash=hash_password("fixture-password"),
        status="ACTIVE",
    )
    db.add(account)
    db.commit()
    svc = IdentityService(db)
    pair = svc.login_web("preexisting-web", "fixture-password")
    session_id = db.scalar(
        select(AuthSession.id).where(
            AuthSession.refresh_token_hash == hash_token(pair.refresh_token)
        )
    )
    staff.user_id = account.id
    db.commit()
    with pytest.raises(UnauthenticatedError):
        svc.refresh(pair.refresh_token)
    db.rollback()
    with pytest.raises(UnauthenticatedError):
        svc.resolve_session_user(account.id, session_id)


def test_admin_web_account_remains_available_when_explicitly_linked_to_temporary_profile(campus):
    from app.core.security import hash_password
    from app.modules.identity.service import IdentityService

    tool, db, _, _, _, sid = onboarding(campus)
    plan = tool.preview(sid)
    result = tool.confirm(plan, decisions(plan))
    staff = db.get(FacultyStaff, int(result["staff"][0]["staff_id"]))
    admin = db.get(UserAccount, campus[2].id)
    admin.username = "fixture-admin"
    admin.password_hash = hash_password("fixture-password")
    staff.user_id = admin.id
    db.commit()
    assert IdentityService(db).login_web("fixture-admin", "fixture-password").access_token


def test_cli_preview_review_confirm_and_export(campus, tmp_path, monkeypatch, capsys):
    import json
    import sys

    from app.cli import staff_onboarding as cli

    tool, db, actor, cid, _, sid = onboarding(campus)
    monkeypatch.setattr(cli, "get_session_factory", lambda: lambda: db)
    base = ["staff_onboarding", "--actor-id", str(actor.id), "--college-id", str(cid)]
    plan_file, result_file = tmp_path / "plan.json", tmp_path / "result.json"
    monkeypatch.setattr(
        sys, "argv", base + ["preview", "--semester-id", str(sid), "--output", str(plan_file)]
    )
    cli.main()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    review_file = tmp_path / "plan-review.json"
    review_file.write_text(json.dumps(decisions(plan), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        base
        + [
            "confirm",
            "--plan",
            str(plan_file),
            "--review",
            str(review_file),
            "--output",
            str(result_file),
        ],
    )
    cli.main()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    arguments = [arg for row in result["staff"] for arg in ("--staff-id", row["staff_id"])]
    monkeypatch.setattr(
        sys, "argv", base + ["export", *arguments, "--output", str(tmp_path / "credentials.csv")]
    )
    cli.main()
    assert (tmp_path / "credentials.csv").exists()
    assert len(db.scalars(select(FacultyStaff)).all()) == 2
    assert "TMP_" not in capsys.readouterr().out


def test_mysql_concurrent_confirm_returns_one_receipt_without_duplicate_profiles(campus):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.modules.importer.scoped_service import ScopedImporterService
    from app.modules.importer.staff_onboarding import StaffOnboarding
    from sqlalchemy.orm import Session

    tool, db, actor, cid, _, sid = onboarding(campus)
    if db.get_bind().dialect.name != "mysql":
        pytest.skip("仅在隔离 MySQL 验证行锁和重复确认竞争")
    plan = tool.preview(sid)
    review = decisions(plan)
    db.commit()
    barrier = Barrier(2)
    engine = db.get_bind()

    def confirm_once():
        with Session(engine, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            return StaffOnboarding(ScopedImporterService(session, actor, cid)).confirm(plan, review)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [
            future.result(timeout=30)
            for future in [pool.submit(confirm_once), pool.submit(confirm_once)]
        ]
    assert first == second
    assert db.scalar(select(func.count()).select_from(FacultyStaff)) == 2
