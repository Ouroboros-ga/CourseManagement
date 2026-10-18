"""教职工绑定、本人依赖与 /me 摘要的定向回归；独立内存库，不连接真实 MySQL。

覆盖 T01 验收：绑定码只存摘要且单次原子核销、抢绑仅一次成功、已有管理员明确
关联而非姓名合并、受限会话仅放行身份白名单、撤权后下一次请求即被拒绝。
"""

import runpy
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import utcnow
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import hash_token
from app.models import Base
from app.modules.academic.models import TeachingClass
from app.modules.academic.staff_models import FacultyStaff
from app.modules.identity.models import UserAccount
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.staff_binding import StaffBindingService
from app.modules.identity.staff_binding_models import StaffBindingToken
from app.modules.identity.staff_deps import require_current_staff, resolve_app_context
from app.modules.identity.staff_scope import teaching_class_condition
from sqlalchemy import create_engine, event, inspect, select

from tests.unit.test_staff_management import create_staff, page, service  # noqa: F401
from tests.unit.test_staff_management import staff_env as staff_env_fixture


@pytest.fixture
def staff_env():
    yield from staff_env_fixture.__wrapped__()


def binding(env, college_id=1):
    return StaffBindingService(env["db"], college_id=college_id)


def bind(env, staff_row, account):
    _token_id, code, _expires = binding(env).issue_token(
        actor=env["admin"], staff_id=int(staff_row["id"])
    )
    return binding(env).redeem(
        user_id=account.id, staff_no=staff_row["staff_no"], binding_code=code
    )


def test_binding_token_persists_only_a_digest_and_can_be_revoked(staff_env):
    staff = create_staff(staff_env, "00001")
    token_id, plaintext, expires_at = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"]), reason="迎新"
    )
    row = staff_env["db"].get(StaffBindingToken, token_id)
    assert row.token_hash == hash_token(plaintext)
    assert plaintext not in row.token_hash
    assert row.status == "UNUSED"
    assert row.expires_at == expires_at
    assert row.staff_id == int(staff["id"])

    # 未核销可作废，且重复作废幂等。
    assert binding(staff_env).revoke_token(actor=staff_env["admin"], token_id=token_id) == token_id
    assert staff_env["db"].get(StaffBindingToken, token_id).status == "EXPIRED"
    assert binding(staff_env).revoke_token(actor=staff_env["admin"], token_id=token_id) == token_id

    # 已核销的码不可作废。
    _used_id, used_code, _e = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"])
    )
    binding(staff_env).redeem(
        user_id=staff_env["accounts"]["wechat"].id, staff_no="00001", binding_code=used_code
    )
    with pytest.raises(ConflictError):
        binding(staff_env).revoke_token(actor=staff_env["admin"], token_id=_used_id)

    foreign = create_staff(staff_env, "00002", college_id=2)
    with pytest.raises(NotFoundError):
        binding(staff_env).issue_token(actor=staff_env["admin"], staff_id=int(foreign["id"]))


def test_redeem_links_the_authenticated_account_without_granting_roles(staff_env):
    staff = create_staff(staff_env, "00001", "同名")
    account = staff_env["accounts"]["wechat"]
    result = bind(staff_env, staff, account)

    assert result["staff_no"] == "00001"
    assert result["user_id"] == str(account.id)
    profile = staff_env["db"].get(FacultyStaff, int(staff["id"]))
    assert profile.user_id == account.id
    assert profile.lock_version == staff["lock_version"] + 1
    # 绑定只激活本人入口，不派生 TEACHER_ADMIN 或任何全院权限。
    assert IdentityRepository(staff_env["db"]).list_role_codes(account.id) == []
    assert IdentityRepository(staff_env["db"]).list_effective_permissions(account.id) == []


def test_the_same_code_cannot_be_redeemed_twice(staff_env):
    staff = create_staff(staff_env, "00001")
    token_id, code, _expires = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"])
    )
    binding(staff_env).redeem(
        user_id=staff_env["accounts"]["wechat"].id, staff_no="00001", binding_code=code
    )
    assert staff_env["db"].get(StaffBindingToken, token_id).status == "USED"
    with pytest.raises(ConflictError):
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["teacher"].id, staff_no="00001", binding_code=code
        )
    assert staff_env["db"].get(FacultyStaff, int(staff["id"])).user_id == 3


def test_two_accounts_competing_for_one_profile_leave_a_single_binding(staff_env):
    staff = create_staff(staff_env, "00001")
    _first, code_one, _e1 = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"])
    )
    _second, code_two, _e2 = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"])
    )
    binding(staff_env).redeem(
        user_id=staff_env["accounts"]["wechat"].id, staff_no="00001", binding_code=code_one
    )
    with pytest.raises(ConflictError):
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["teacher"].id, staff_no="00001", binding_code=code_two
        )
    assert staff_env["db"].get(FacultyStaff, int(staff["id"])).user_id == 3


def test_mismatched_or_expired_codes_do_not_link_anyone(staff_env):
    staff = create_staff(staff_env, "00001")
    token_id, code, _expires = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(staff["id"])
    )
    with pytest.raises(AppError) as mismatch:
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["wechat"].id, staff_no="00009", binding_code=code
        )
    assert mismatch.value.http_status == 422
    assert staff_env["db"].get(StaffBindingToken, token_id).failed_attempts == 1
    assert staff_env["db"].get(FacultyStaff, int(staff["id"])).user_id is None

    row = staff_env["db"].get(StaffBindingToken, token_id)
    row.expires_at = utcnow() - timedelta(minutes=1)
    staff_env["db"].commit()
    with pytest.raises(ConflictError):
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["wechat"].id, staff_no="00001", binding_code=code
        )
    assert staff_env["db"].get(StaffBindingToken, token_id).status == "EXPIRED"
    assert staff_env["db"].get(FacultyStaff, int(staff["id"])).user_id is None

    with pytest.raises(AppError):
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["wechat"].id, staff_no="00001", binding_code="ZZZZZZ"
        )


def test_an_existing_admin_is_linked_explicitly_and_never_merged_by_name(staff_env):
    admin_side = create_staff(staff_env, "00001", "同名")
    other = create_staff(staff_env, "00002", "同名")
    account = staff_env["accounts"]["teacher"]

    bind(staff_env, admin_side, account)
    assert staff_env["db"].get(FacultyStaff, int(admin_side["id"])).user_id == account.id
    # 同名档案不会被顺手合并进同一个账号。
    assert staff_env["db"].get(FacultyStaff, int(other["id"])).user_id is None
    # 既有管理员身份保持不变，工号+绑定码是唯一关联依据。
    assert IdentityRepository(staff_env["db"]).list_role_codes(account.id) == ["TEACHER_ADMIN"]

    bound = create_staff(staff_env, "00003", "同名")
    bind(staff_env, bound, staff_env["accounts"]["wechat"])
    _token_id, code, _expires = binding(staff_env).issue_token(
        actor=staff_env["admin"], staff_id=int(bound["id"])
    )
    with pytest.raises(ConflictError):
        binding(staff_env).redeem(
            user_id=staff_env["accounts"]["admin"].id, staff_no="00003", binding_code=code
        )


def test_revoked_access_is_refused_by_the_next_request(staff_env):
    staff = create_staff(staff_env, "00001")
    bind(staff_env, staff, staff_env["accounts"]["wechat"])
    actor = staff_env["plain"]
    db = staff_env["db"]

    assert require_current_staff(actor, db).staff_no == "00001"

    profile = db.get(FacultyStaff, int(staff["id"]))
    profile.status = "INACTIVE"
    db.commit()
    with pytest.raises(PermissionDeniedError):
        require_current_staff(actor, db)

    profile.status = "ACTIVE"
    db.commit()
    account = db.get(UserAccount, profile.user_id)
    account.status = "DISABLED"
    db.commit()
    with pytest.raises(PermissionDeniedError):
        require_current_staff(actor, db)

    account.status = "ACTIVE"
    db.commit()
    service(staff_env).unlink_account(
        int(staff["id"]), {"lock_version": profile.lock_version, "reason": "换单位"}
    )
    assert db.get(FacultyStaff, int(staff["id"])).user_id is None
    with pytest.raises(PermissionDeniedError):
        require_current_staff(actor, db)
    # 学院管理入口对同一账号始终关闭。
    with pytest.raises(PermissionDeniedError):
        service(staff_env, actor).list_staff(page())


def test_app_context_reports_modes_and_views_without_new_permissions(staff_env):
    staff = create_staff(staff_env, "00001")
    bind(staff_env, staff, staff_env["accounts"]["wechat"])
    staff_service = service(staff_env)
    staff_service.create_teaching_assignment(
        {
            "staff_id": staff["id"],
            "semester_id": "1",
            "anchor_type": "LOCAL",
            "teaching_class_id": "1",
            "effective_from": "2026-09-01",
        }
    )

    context = resolve_app_context(staff_env["db"], staff_env["plain"])
    assert context["modes"] == ["staff"]
    assert context["default_mode"] == "staff"
    assert context["staff"]["staff_no"] == "00001"
    assert context["staff"]["views"] == {"teaching": True, "responsible": False}

    staff_service.create_responsibility(
        {
            "staff_id": staff["id"],
            "administrative_class_id": "1",
            "duty": "COUNSELOR",
            "effective_from": "2026-09-01",
        }
    )
    assert resolve_app_context(staff_env["db"], staff_env["plain"])["staff"]["views"] == {
        "teaching": True,
        "responsible": True,
    }

    # 摘要不改变身份集合：既没有新增角色，也没有全院读取权限。
    assert staff_env["plain"].roles == []
    assert staff_env["plain"].permissions == []
    with pytest.raises(PermissionDeniedError):
        service(staff_env, staff_env["plain"]).list_staff(page())

    dual = create_staff(staff_env, "00002")
    bind(staff_env, dual, staff_env["accounts"]["admin"])
    admin_context = resolve_app_context(staff_env["db"], staff_env["admin"])
    assert admin_context["modes"] == ["staff"]
    assert admin_context["default_mode"] == "staff"
    assert admin_context["administrator"] is True

    # 停用档案后本人入口与摘要同时收敛。
    staff_env["db"].get(FacultyStaff, int(staff["id"])).status = "INACTIVE"
    staff_env["db"].commit()
    revoked = resolve_app_context(staff_env["db"], staff_env["plain"])
    assert revoked["modes"] == []
    assert revoked["staff"] is None
    assert revoked["default_mode"] is None


def teaching_visible(env, user_id, on):
    return sorted(
        env["db"].scalars(
            select(TeachingClass.id).where(
                teaching_class_condition(user_id, occurrence_on=on, as_of=on)
            )
        )
    )


def test_ended_appointment_stops_the_self_view_without_blocking_the_profile(staff_env):
    staff = create_staff(staff_env, "00001")
    bind(staff_env, staff, staff_env["accounts"]["wechat"])
    staff_service = service(staff_env)
    created = staff_service.create_teaching_assignment(
        {
            "staff_id": staff["id"],
            "semester_id": "1",
            "anchor_type": "LOCAL",
            "teaching_class_id": "1",
            "effective_from": "2026-09-01",
        }
    )
    user_id = staff_env["accounts"]["wechat"].id
    assert teaching_visible(staff_env, user_id, date(2026, 9, 20)) == [1]

    staff_service.end_teaching_assignment(
        int(created["id"]),
        {"effective_to": "2026-10-01", "lock_version": created["lock_version"]},
    )
    assert teaching_visible(staff_env, user_id, date(2026, 10, 1)) == []
    assert teaching_visible(staff_env, user_id, date(2026, 9, 30)) == [1]
    # 关系结束不撤销档案本身：本人入口仍可用，只是没有授课视图。
    assert require_current_staff(staff_env["plain"], staff_env["db"]).staff_no == "00001"
    assert resolve_app_context(staff_env["db"], staff_env["plain"])["staff"]["views"] == {
        "teaching": False,
        "responsible": False,
    }


def test_staff_binding_migration_matches_the_model():
    root = Path(__file__).parents[2] / "migrations/versions"
    foundation = runpy.run_path(str(root / "f26a1017s001_staff_foundation.py"))
    binding = runpy.run_path(str(root / "f26a1017s002_staff_binding.py"))
    assert binding["down_revision"] == foundation["revision"]

    foundation_tables = {
        "faculty_staff",
        "teaching_staff_assignment",
        "class_staff_responsibility",
    }
    staff_tables = foundation_tables | {"staff_binding_token"}
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    with engine.begin() as db:
        Base.metadata.create_all(
            db, tables=[t for t in Base.metadata.sorted_tables if t.name not in staff_tables]
        )
        before = set(inspect(db).get_table_names())
        with Operations.context(MigrationContext.configure(db)):
            foundation["upgrade"]()
            assert set(inspect(db).get_table_names()) == before | foundation_tables
            binding["upgrade"]()
            assert set(inspect(db).get_table_names()) == before | staff_tables
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
            binding["downgrade"]()
            assert set(inspect(db).get_table_names()) == before | foundation_tables
    engine.dispose()


def test_duplicate_codes_on_different_profiles_are_scoped_by_staff_number(staff_env, monkeypatch):
    monkeypatch.setattr(
        "app.modules.identity.staff_binding.generate_friendly_binding_code", lambda _: "ABC234"
    )
    first = create_staff(staff_env, "00001")
    second = create_staff(staff_env, "00002")
    for profile in (first, second):
        binding(staff_env).issue_token(actor=staff_env["admin"], staff_id=int(profile["id"]))
    result = binding(staff_env).redeem(
        user_id=3, staff_no="00002", binding_code="ABC234"
    )
    assert result["staff_id"] == second["id"]
    assert staff_env["db"].get(FacultyStaff, int(first["id"])).user_id is None


def test_issue_retries_a_code_already_used_by_the_same_profile(staff_env, monkeypatch):
    profile = create_staff(staff_env, "00001")
    codes = iter(["ABC234", "ABC234", "XYZ789"])
    monkeypatch.setattr(
        "app.modules.identity.staff_binding.generate_friendly_binding_code", lambda _: next(codes)
    )
    svc = binding(staff_env)
    first_id, _, _ = svc.issue_token(actor=staff_env["admin"], staff_id=int(profile["id"]))
    svc.revoke_token(actor=staff_env["admin"], token_id=first_id)
    _, code, _ = svc.issue_token(actor=staff_env["admin"], staff_id=int(profile["id"]))
    assert code == "XYZ789"
    assert svc.redeem(user_id=3, staff_no="00001", binding_code=code)["user_id"] == "3"


def test_legacy_expired_duplicate_does_not_hide_a_valid_code(staff_env):
    profile = create_staff(staff_env, "00001")
    db = staff_env["db"]
    db.add_all([
        StaffBindingToken(
            staff_id=int(profile["id"]), token_hash=hash_token("ABC234"),
            status=status, expires_at=utcnow() + timedelta(minutes=minutes),
        ) for status, minutes in [("EXPIRED", -1), ("UNUSED", 10)]
    ])
    db.commit()
    assert binding(staff_env).redeem(
        user_id=3, staff_no="00001", binding_code="ABC234"
    )["staff_id"] == profile["id"]


def test_ambiguous_legacy_active_codes_are_rejected_without_guessing(staff_env):
    profile = create_staff(staff_env, "00001")
    db = staff_env["db"]
    for _ in range(2):
        db.add(StaffBindingToken(
            staff_id=int(profile["id"]), token_hash=hash_token("ABC234"), status="UNUSED",
            expires_at=utcnow() + timedelta(minutes=10),
        ))
    db.commit()
    with pytest.raises(AppError) as exc:
        binding(staff_env).redeem(user_id=3, staff_no="00001", binding_code="ABC234")
    assert exc.value.http_status == 422
    assert db.get(FacultyStaff, int(profile["id"])).user_id is None


def test_me_openapi_describes_the_existing_identity_context():
    from app.main import create_app

    schema = create_app().openapi()
    response = schema["paths"]["/api/v1/me"]["get"]["responses"]["200"]["content"]
    ref = response["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
    envelope = schema["components"]["schemas"][ref]
    assert "data" in envelope["properties"]
    assert "app_context" in schema["components"]["schemas"]["CurrentUserResponse"]["properties"]


@pytest.mark.parametrize("actor_key,bind_profile,modes", [
    ("plain", False, []), ("plain", True, ["staff"]),
    ("student_staff", False, ["student"]), ("student_staff", True, ["student", "staff"]),
    ("admin", False, []), ("admin", True, ["staff"]),
])
def test_me_response_model_preserves_identity_combinations(
    staff_env, actor_key, bind_profile, modes
):
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.identity.deps import get_current_user
    from fastapi.testclient import TestClient

    actor = staff_env[actor_key]
    if bind_profile:
        profile = create_staff(staff_env, "001234")
        bind(staff_env, profile, staff_env["db"].get(UserAccount, actor.id))
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: staff_env["db"]
    with TestClient(app) as client:
        response = client.get("/api/v1/me")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["app_context"]["modes"] == modes
    assert data["binding_required"] == actor.pre_binding
    assert data["roles"] == actor.roles
