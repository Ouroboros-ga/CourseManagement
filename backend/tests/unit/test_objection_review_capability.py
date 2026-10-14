"""功能按项授予时，异议审核含本次改判能力，不授予独立手工更正权限。"""

import pytest
from app import models as _orm_models  # noqa: F401 - 注册完整 ORM 外键目标，不依赖测试收集顺序。
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.attendance.models import AttendanceRecord, AttendanceRecordVersion
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.attendance.service import AttendanceService
from app.modules.identity.models import Permission, Role, RolePermission
from app.modules.identity.repository import IdentityRepository
from app.modules.objection.models import Objection
from app.modules.objection.schemas import ObjectionFinalReviewRequest
from sqlalchemy import delete, select

from tests.unit.test_objection_single_review import setup_review as setup_review


def _grant_only(db, actions):
    # 在独立测试库按项授予角色能力，不依赖其他任务新增的任命数据模型。
    role_id = db.scalar(select(Role.id).where(Role.code == "STUDENT_AFFAIRS_MANAGER"))
    db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for action in actions:
        permission_id = db.scalar(select(Permission.id).where(Permission.code == action))
        db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    db.commit()


def test_review_only_approval_corrects_attendance(setup_review):
    db, service, actor, bumps = setup_review
    _grant_only(db, ["objection.final_review"])
    permissions = IdentityRepository(db).list_effective_permissions(actor.id)
    assert "objection.final_review" in permissions
    assert "attendance.correct" not in permissions
    result = service.final_review(
        actor,
        1,
        ObjectionFinalReviewRequest(decision="APPROVED", final_type="NORMAL", current_version=1),
        None,
    )
    assert result.final_status == "APPROVED"
    assert result.final_reviewed_username == "reviewer"
    assert db.get(AttendanceRecord, 1).effective_type == "NORMAL"
    assert db.get(AttendanceRecord, 1).current_version == 2
    assert db.scalar(select(AttendanceRecordVersion)).source_type == "OBJECTION_FINAL"
    assert bumps == [1]
    assert "attendance.correct" not in IdentityRepository(db).list_effective_permissions(actor.id)


def test_review_only_rejection_keeps_attendance(setup_review):
    db, service, actor, bumps = setup_review
    _grant_only(db, ["objection.final_review"])
    result = service.final_review(
        actor, 1, ObjectionFinalReviewRequest(decision="REJECTED", current_version=1), None
    )
    assert result.final_status == "REJECTED"
    assert db.get(AttendanceRecord, 1).effective_type == "ABSENT"
    assert db.get(AttendanceRecord, 1).current_version == 1
    assert bumps == []


def test_review_only_cannot_overwrite_stale_version(setup_review):
    db, service, actor, _ = setup_review
    _grant_only(db, ["objection.final_review"])
    with pytest.raises(ConflictError):
        service.final_review(
            actor,
            1,
            ObjectionFinalReviewRequest(
                decision="APPROVED", final_type="NORMAL", current_version=2
            ),
            None,
        )
    assert db.get(Objection, 1).final_status == "PENDING"
    assert db.get(AttendanceRecord, 1).current_version == 1


def test_manual_correction_permission_does_not_grant_review(setup_review):
    db, service, actor, _ = setup_review
    _grant_only(db, ["attendance.correct"])
    with pytest.raises(PermissionDeniedError):
        service.final_review(
            actor,
            1,
            ObjectionFinalReviewRequest(
                decision="APPROVED", final_type="NORMAL", current_version=1
            ),
            None,
        )
    assert db.get(Objection, 1).final_status == "PENDING"
    assert db.get(AttendanceRecord, 1).effective_type == "ABSENT"


def test_review_permission_does_not_grant_manual_correction(setup_review):
    db, _, actor, _ = setup_review
    _grant_only(db, ["objection.final_review"])
    with pytest.raises(PermissionDeniedError):
        AttendanceService(db).correct(
            actor, 1, AttendanceCorrectionRequest(attendance_type="NORMAL", current_version=1), None
        )
    assert db.get(AttendanceRecord, 1).effective_type == "ABSENT"
