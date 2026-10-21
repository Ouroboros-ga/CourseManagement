"""独立MySQL验证微信换绑归属及账号锁；必须经 *_test 夹具目标保护。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.exceptions import AppError
from app.modules.academic.models import AdministrativeClass, Semester
from app.modules.identity.models import AuthSession, UserAccount, WechatIdentity
from app.modules.identity.seed import sync_registry
from app.modules.identity.service import IdentityService
from app.modules.organization.models import College, School
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit import test_student_wechat_rebind as unit
from tests.unit.test_student_wechat_rebind import code, seed

pytestmark = pytest.mark.integration


@pytest.fixture
def env(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", False)
    sync_registry(session)
    session.add(School(id=1, code="test", name="测试学校"))
    session.flush()
    session.add(College(id=1, school_id=1, code="test", name="测试学院"))
    session.add(
        Semester(
            id=1,
            code="test",
            name="测试学期",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 2, 1),
            first_monday=date(2026, 8, 31),
            total_weeks=22,
        )
    )
    session.flush()
    session.add(AdministrativeClass(id=1, college_id=1, class_code="test", class_name="测试班"))
    admin = UserAccount(display_name="测试管理员", status="ACTIVE")
    plain = UserAccount(display_name="未绑定测试微信", status="ACTIVE")
    session.add_all([admin, plain])
    session.flush()
    repo = IdentityService(session)._repo
    repo.grant_role(admin.id, repo.get_role_by_code("SUPER_ADMIN").id)
    session.commit()
    return {"db": session, "admin": admin, "accounts": {"wechat": plain}}


@pytest.mark.parametrize(
    "test_name",
    [
        "test_unbind_keeps_student_business_uid_and_role",
        "test_two_wechat_rebind_preserves_pending_and_submitted_records",
        "test_admin_cannot_relabel_uid_with_inspection_history",
        "test_redeem_refuses_disabled_existing_account",
        "test_claim_moves_only_live_wechat_sessions_and_refresh_keeps_student_uid",
        "test_stale_session_cannot_unbind_again_after_wechat_has_changed",
        "test_orphaned_history_cannot_be_rebound_to_another_student",
        "test_claim_cannot_take_over_management_account",
    ],
)
def test_mysql_business_invariants(env, test_name):
    getattr(unit, test_name)(env)


def race(engine, operations):
    barrier = Barrier(len(operations))

    def execute(operation):
        with Session(engine, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            try:
                operation(IdentityService(db))
                return "ok"
            except AppError:
                db.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(execute, operations))


def test_concurrent_unbind_only_one_detaches(env, engine):
    _, b, owner, _, wx_a, _, old = seed(env)
    uid, sid = owner.id, old.id
    env["db"].commit()
    outcomes = race(engine, [lambda service: service.student_self_unbind(uid, session_id=sid)] * 2)
    assert sorted(outcomes) == ["ok", "rejected"]
    db = env["db"]
    db.expire_all()
    assert db.get(UserAccount, uid).student_id == b.id
    assert db.get(WechatIdentity, wx_a.id).user_id != uid


def test_two_wechat_claim_same_student_only_one_wins(env, engine):
    _, b, owner, other, _, _, _ = seed(env)
    db = env["db"]
    IdentityService(db).student_self_unbind(owner.id)
    third = UserAccount(display_name="第三微信", status="ACTIVE")
    db.add(third)
    db.flush()
    db.add(WechatIdentity(user_id=third.id, appid="test", openid="wx-c"))
    db.commit()
    code(db, b, "claim-1")
    code(db, b, "claim-2")
    ids = [other.id, third.id]
    sno = b.student_no
    outcomes = race(
        engine,
        [
            lambda service: service.bind_student(ids[0], sno, "claim-1"),
            lambda service: service.bind_student(ids[1], sno, "claim-2"),
        ],
    )
    assert sorted(outcomes) == ["ok", "rejected"]
    db.expire_all()
    assert (
        len(db.scalars(select(WechatIdentity).where(WechatIdentity.user_id == owner.id)).all()) == 1
    )


def test_refresh_cannot_survive_concurrent_unbind(env, engine):
    _, _, owner, _, _, _, old = seed(env)
    uid, sid = owner.id, old.id
    env["db"].commit()
    outcomes = race(
        engine,
        [
            lambda service: service.student_self_unbind(uid, session_id=sid),
            lambda service: service.refresh("refresh-a"),
        ],
    )
    assert outcomes[0] == "ok"
    env["db"].expire_all()
    assert (
        not env["db"]
        .scalars(
            select(AuthSession).where(
                AuthSession.user_id == uid,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
        .all()
    )


def test_login_cannot_issue_stale_student_session_during_unbind(env, engine, monkeypatch):
    from app.modules.identity.wechat import MockWechatCode2SessionClient

    _, _, owner, _, _, _, old = seed(env)
    uid, sid = owner.id, old.id
    monkeypatch.setattr(get_settings(), "wechat_login_enabled", True)
    monkeypatch.setattr(get_settings(), "wechat_appid", "test")
    env["db"].commit()

    def login(service):
        service._wechat_client = MockWechatCode2SessionClient(code_to_openid={"login": "wx-a"})
        service.login_wechat("login")

    outcomes = race(
        engine, [lambda service: service.student_self_unbind(uid, session_id=sid), login]
    )
    assert outcomes[0] == "ok"
    env["db"].expire_all()
    assert (
        not env["db"]
        .scalars(
            select(AuthSession).where(
                AuthSession.user_id == uid,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
        .all()
    )
