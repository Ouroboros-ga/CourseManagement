"""院级配置的真实数据库回归；不触碰运行库或 MySQL 集成夹具。"""

from datetime import timedelta
import os

import pytest
from app.core.database import utcnow
from app.core.exceptions import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def campus():
    from app import models  # noqa: F401
    from app.core.database import Base
    from app.modules.organization.service import CampusService

    mysql_url = os.environ.get("CAMPUS_TEST_DATABASE_URL")
    if mysql_url:
        from sqlalchemy.engine import make_url
        url = make_url(mysql_url)
        if url.get_backend_name() != "mysql" or not (url.database or "").endswith("_test"):
            raise RuntimeError("学院真实数据库回归仅允许独立 MySQL *_test 库")
        engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        event.listen(
            engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
        )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        admin = UserAccount(display_name="超管", status="ACTIVE")
        teacher = UserAccount(display_name="教师", status="ACTIVE")
        db.add_all([admin, teacher])
        role = Role(code="SUPER_ADMIN", name="超管")
        db.add(role)
        db.flush()
        db.add(UserRole(user_id=admin.id, role_id=role.id))
        db.commit()
        actor = CurrentUser(admin.id, None, "超管", "ACTIVE", ["SUPER_ADMIN"], [])
        reader = CurrentUser(teacher.id, None, "教师", "ACTIVE", ["TEACHER_ADMIN"], [])
        service = CampusService(db)
        school = service.create_school(actor, {"code": "S", "name": "学校"})
        a = service.create_college(actor, int(school["id"]), {"code": "A", "name": "甲院"})
        b = service.create_college(actor, int(school["id"]), {"code": "B", "name": "乙院"})
        yield service, db, actor, reader, a, b
    engine.dispose()


def grant(service, admin, reader, college, actions, **extra):
    return service.create_grant(
        admin,
        int(college["id"]),
        {
            "user_id": str(reader.id),
            "actions": actions,
            **extra,
        },
    )


def test_action_and_college_are_not_unioned(campus):
    service, _, admin, teacher, a, b = campus
    grant(service, admin, teacher, a, ["academic.course_type.read", "academic.course_type.manage"])
    grant(service, admin, teacher, b, ["academic.course_type.read"])
    service.create_type(teacher, int(a["id"]), {"name": "集中训练"})
    assert service.list_types(teacher, int(b["id"])) == []
    with pytest.raises(PermissionDeniedError):
        service.create_type(teacher, int(b["id"]), {"name": "集中训练"})


def test_role_label_cannot_grant_college_access(campus):
    service, _, _, teacher, a, _ = campus
    assert service.workspaces(teacher) == []
    with pytest.raises(NotFoundError):
        service.list_types(teacher, int(a["id"]))


def test_bound_teacher_has_all_primary_actions_and_binding_change_is_fresh(campus):
    from app.modules.academic.enrollment_models import TeacherCollegeBinding
    from app.modules.identity.authorization import CAMPUS_ACTIONS

    service, db, admin, teacher, a, b = campus
    role = Role(code="TEACHER_ADMIN", name="教师")
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=teacher.id, role_id=role.id))
    binding = TeacherCollegeBinding(user_id=teacher.id, college_id=int(a["id"]))
    db.add(binding)
    db.commit()
    assert service.capabilities(teacher, int(a["id"]))["capabilities"] == sorted(CAMPUS_ACTIONS)
    with pytest.raises(NotFoundError):
        service.list_types(teacher, int(b["id"]))
    grant(service, admin, teacher, b, ["academic.course_type.read"])
    assert service.list_types(teacher, int(b["id"])) == []
    with pytest.raises(PermissionDeniedError):
        service.create_type(teacher, int(b["id"]), {"name": "无权写入"})
    binding.college_id = int(b["id"])
    db.commit()
    assert service.capabilities(teacher, int(b["id"]))["capabilities"] == sorted(CAMPUS_ACTIONS)
    with pytest.raises(NotFoundError):
        service.list_types(teacher, int(a["id"]))
    with pytest.raises(PermissionDeniedError):
        service.create_school(teacher, {"code": "BAD", "name": "校级权限不能派生"})


def test_expired_grant_and_revoke_take_effect(campus):
    service, _, admin, teacher, a, _ = campus
    old = grant(
        service,
        admin,
        teacher,
        a,
        ["academic.course_type.read"],
        expires_at=utcnow() - timedelta(seconds=1),
    )
    assert old["id"]
    assert service.workspaces(teacher) == []
    current = grant(service, admin, teacher, a, ["academic.course_type.read"])
    assert service.workspaces(teacher)
    service.revoke_grant(admin, int(a["id"]), int(current["id"]), current["lock_version"])
    assert service.workspaces(teacher) == []


def test_disabled_account_and_stale_superadmin_claim_are_rechecked(campus):
    service, db, admin, teacher, a, _ = campus
    grant(service, admin, teacher, a, ["academic.course_type.read"])
    db.get(UserAccount, teacher.id).status = "DISABLED"
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service.workspaces(teacher)
    db.delete(db.execute(select(UserRole).where(UserRole.user_id == admin.id)).scalar_one())
    db.commit()
    with pytest.raises(PermissionDeniedError):
        service.create_school(admin, {"code": "FAKE", "name": "不应创建"})


def test_dynamic_types_rename_conflicts_and_bigint_strings(campus):
    service, _, admin, _, a, b = campus
    row = service.create_type(admin, int(a["id"]), {"name": "  集中训练  "})
    assert row["name"] == "集中训练" and isinstance(row["id"], str)
    assert isinstance(row["college_id"], str)
    with pytest.raises(ConflictError):
        service.create_type(admin, int(a["id"]), {"name": "集中训练"})
    assert service.create_type(admin, int(b["id"]), {"name": "集中训练"})
    renamed = service.update_type(
        admin, int(a["id"]), int(row["id"]), {"name": "训练", "lock_version": row["lock_version"]}
    )
    assert renamed["id"] == row["id"] and renamed["code"] == row["code"]
    with pytest.raises(ConflictError):
        service.update_type(
            admin,
            int(a["id"]),
            int(row["id"]),
            {"name": "旧写", "lock_version": row["lock_version"]},
        )
    with pytest.raises(NotFoundError):
        service.update_type(
            admin,
            int(b["id"]),
            int(row["id"]),
            {"name": "越院", "lock_version": renamed["lock_version"]},
        )


def test_group_publication_uses_explicit_types_and_immutable_versions(campus):
    service, _, admin, _, a, _ = campus
    morning = service.create_type(admin, int(a["id"]), {"name": "早自习"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "早查组", "owner_user_id": str(admin.id)}
    )
    configuration = {
        "lock_version": group["lock_version"],
        "course_type_ids": [morning["id"]],
        "default_effect": "BLOCK",
        "type_overrides": {morning["id"]: "ALLOW"},
    }
    published = service.publish_group(admin, int(a["id"]), int(group["id"]), configuration)
    service.create_type(admin, int(a["id"]), {"name": "晚自习"})
    current = service.list_groups(admin, int(a["id"]))[0]
    assert current["configuration"]["course_type_ids"] == [morning["id"]]
    assert current["status"] == "DRAFT"
    activated = service.update_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"status": "ACTIVE", "lock_version": published["lock_version"]},
    )
    assert activated["status"] == "ACTIVE"
    with pytest.raises(ConflictError):
        service.publish_group(admin, int(a["id"]), int(group["id"]), configuration)
    with pytest.raises(ConflictError):
        service.delete_type(admin, int(a["id"]), int(morning["id"]), morning["lock_version"])


def test_foreign_or_empty_group_scope_is_rejected_atomically(campus):
    service, _, admin, _, a, b = campus
    foreign = service.create_type(admin, int(b["id"]), {"name": "早自习"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "组", "owner_user_id": str(admin.id)}
    )
    for ids in ([], [foreign["id"]]):
        with pytest.raises((ConflictError, NotFoundError)):
            service.publish_group(
                admin,
                int(a["id"]),
                int(group["id"]),
                {"lock_version": group["lock_version"], "course_type_ids": ids},
            )
    assert service.list_groups(admin, int(a["id"]))[0]["configuration"] is None


def test_member_permission_does_not_publish_config(campus):
    service, _, admin, teacher, a, _ = campus
    grant(service, admin, teacher, a, ["volunteer.group.read", "volunteer.member.manage"])
    group = service.create_group(
        admin, int(a["id"]), {"name": "组", "owner_user_id": str(admin.id)}
    )
    kind = service.create_type(admin, int(a["id"]), {"name": "类型"})
    with pytest.raises(PermissionDeniedError):
        service.publish_group(
            teacher,
            int(a["id"]),
            int(group["id"]),
            {"lock_version": group["lock_version"], "course_type_ids": [kind["id"]]},
        )


def test_scope_checks_full_class_set_before_sampling():
    from app.modules.volunteer.policy import InspectionScope

    scope = InspectionScope(1, frozenset({10}), frozenset({5, 6}))
    assert scope.allows(college_id=1, course_type_id=10, class_ids={5, 6})
    assert not scope.allows(college_id=1, course_type_id=10, class_ids={5, 7})
    assert not scope.allows(college_id=2, course_type_id=10, class_ids={5})
    assert not scope.allows(college_id=1, course_type_id=11, class_ids={5})
    assert not scope.allows(college_id=1, course_type_id=10, class_ids=set())


def test_conflict_rule_matches_own_course_and_specific_override():
    from app.modules.volunteer.policy import course_conflict_effect

    assert course_conflict_effect(10, 100, "BLOCK", {10: "ALLOW"}, {100: "BLOCK"}) == "BLOCK"
    assert course_conflict_effect(10, 101, "BLOCK", {10: "ALLOW"}, {}) == "ALLOW"
    assert course_conflict_effect(11, 101, "BLOCK", {10: "ALLOW"}, {}) == "BLOCK"


def test_delete_unused_group_records_configuration_in_audit(campus):
    from app.modules.audit.models import AuditLog

    service, db, admin, _, a, _ = campus
    group = service.create_group(
        admin, int(a["id"]), {"name": "草稿", "owner_user_id": str(admin.id)}
    )
    service.delete_group(admin, int(a["id"]), int(group["id"]), group["lock_version"])
    assert service.list_groups(admin, int(a["id"])) == []
    kind = service.create_type(admin, int(a["id"]), {"name": "课"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "已有配置", "owner_user_id": str(admin.id)}
    )
    group = service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"lock_version": group["lock_version"], "course_type_ids": [kind["id"]]},
    )
    service.delete_group(admin, int(a["id"]), int(group["id"]), group["lock_version"])
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "campus.group.delete").order_by(AuditLog.id.desc()))
    assert audit.before_json["configuration"]["course_type_ids"] == [kind["id"]]


def test_explicit_null_name_is_not_silently_ignored(campus):
    service, _, admin, _, a, _ = campus
    row = service.create_type(admin, int(a["id"]), {"name": "原名"})
    with pytest.raises(AppError, match="配置格式无效"):
        service.update_type(
            admin, int(a["id"]), int(row["id"]), {"lock_version": row["lock_version"], "name": None}
        )


def test_failed_group_update_cannot_leak_into_later_commit(campus):
    service, _, admin, _, a, _ = campus
    group = service.create_group(
        admin, int(a["id"]), {"name": "原名", "owner_user_id": str(admin.id)}
    )
    with pytest.raises(ConflictError):
        service.update_group(
            admin,
            int(a["id"]),
            int(group["id"]),
            {"lock_version": group["lock_version"], "name": "失败修改", "status": "ACTIVE"},
        )
    service.create_type(admin, int(a["id"]), {"name": "无关课"})
    assert service.list_groups(admin, int(a["id"]))[0]["name"] == "原名"


def test_http_scope_versions_and_unknown_fields(campus):
    from app.core.database import get_db
    from app.modules.identity.deps import get_current_user
    from app.modules.organization.router import require_campus_enabled, router
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    service, db, admin, teacher, a, b = campus
    grant(service, admin, teacher, a, ["academic.course_type.read", "academic.course_type.manage"])
    grant(service, admin, teacher, b, ["academic.course_type.read"])
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: teacher
    app.dependency_overrides[require_campus_enabled] = lambda: None
    app.dependency_overrides[get_db] = lambda: db

    @app.exception_handler(AppError)
    async def error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.http_status, content={"code": exc.code.value, "message": exc.message}
        )

    with TestClient(app) as client:
        created = client.post(f"/api/v1/colleges/{a['id']}/course-types", json={"name": "课"})
        assert created.status_code == 200
        row = created.json()["data"]
        assert isinstance(row["id"], str)
        assert (
            client.post(
                f"/api/v1/colleges/{b['id']}/course-types", json={"name": "越院"}
            ).status_code
            == 403
        )
        path = f"/api/v1/colleges/{a['id']}/course-types/{row['id']}"
        assert client.patch(path, json={"name": "更名", "lock_version": 1}).status_code == 200
        assert client.patch(path, json={"name": "旧写", "lock_version": 1}).status_code == 409
        assert (
            client.patch(path, json={"lock_version": 2, "college_id": b["id"]}).status_code == 422
        )
        assert client.get("/api/v1/me/workspaces").json()["data"][0]["business_ready"] is False


def test_inactive_group_can_update_configuration_before_restoring(campus):
    service, _, admin, _, a, _ = campus
    kind = service.create_type(admin, int(a["id"]), {"name": "课"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "组", "owner_user_id": str(admin.id)}
    )
    group = service.update_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"status": "INACTIVE", "lock_version": group["lock_version"]},
    )
    group = service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {"lock_version": group["lock_version"], "course_type_ids": [kind["id"]]},
    )
    assert group["status"] == "INACTIVE"


def test_single_school_constraint_is_enforced_in_database(campus):
    from app.modules.organization.models import School
    from sqlalchemy.exc import IntegrityError

    _, db, _, _, _, _ = campus
    db.add(School(code="SECOND", name="第二学校"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_http_grant_time_requires_timezone():
    from app.modules.organization.schemas import GrantCreate
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GrantCreate.model_validate(
            {
                "user_id": "1",
                "actions": ["academic.course_type.read"],
                "expires_at": "2027-01-01T00:00:00",
            }
        )
    value = GrantCreate.model_validate(
        {
            "user_id": "1",
            "actions": ["academic.course_type.read"],
            "expires_at": "2027-01-01T08:00:00+08:00",
        }
    )
    assert value.expires_at.hour == 0


def test_schema_rejects_out_of_range_account_id():
    from app.modules.organization.schemas import GrantCreate
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GrantCreate.model_validate(
            {"user_id": str(2**63), "actions": ["academic.course_type.read"]}
        )


def test_normalized_type_name_cannot_overflow_database_column(campus):
    service, _, admin, _, a, _ = campus
    with pytest.raises(AppError):
        service.create_type(admin, int(a["id"]), {"name": "㍿" * 128})


def test_republication_keeps_history_and_separates_conflict_reference(campus):
    from app.modules.volunteer.models import GroupConfigVersion, GroupScopeType

    service, db, admin, _, a, _ = campus
    morning = service.create_type(admin, int(a["id"]), {"name": "早自习"})
    normal = service.create_type(admin, int(a["id"]), {"name": "普通课"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "组", "owner_user_id": str(admin.id)}
    )
    group = service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": group["lock_version"],
            "course_type_ids": [morning["id"]],
            "type_overrides": {normal["id"]: "WARN"},
        },
    )
    first = db.scalar(select(GroupConfigVersion).where(GroupConfigVersion.version == 1))
    reference = db.scalar(
        select(GroupScopeType).where(
            GroupScopeType.config_id == first.id,
            GroupScopeType.course_type_id == int(normal["id"]),
        )
    )
    assert reference.is_inspection_scope is False
    group = service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": group["lock_version"],
            **group["configuration"],
            "course_type_ids": [normal["id"]],
            "type_overrides": {},
        },
    )
    assert first.configuration["course_type_ids"] == [morning["id"]]
    assert group["configuration"]["course_type_ids"] == [normal["id"]]
    assert group["config_version"] == 2


def test_db_composite_reference_cannot_point_to_foreign_type(campus):
    from app.modules.volunteer.models import GroupConfigVersion, GroupScopeType
    from sqlalchemy.exc import IntegrityError

    service, db, admin, _, a, b = campus
    local = service.create_type(admin, int(a["id"]), {"name": "本院课"})
    foreign = service.create_type(admin, int(b["id"]), {"name": "外院课"})
    group = service.create_group(
        admin, int(a["id"]), {"name": "组", "owner_user_id": str(admin.id)}
    )
    service.publish_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": group["lock_version"],
            "course_type_ids": [local["id"]],
        },
    )
    config = db.scalar(
        select(GroupConfigVersion).where(GroupConfigVersion.group_id == int(group["id"]))
    )
    db.add(
        GroupScopeType(
            config_id=config.id,
            college_id=int(a["id"]),
            course_type_id=int(foreign["id"]),
            is_inspection_scope=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
