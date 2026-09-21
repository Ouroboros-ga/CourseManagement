"""权限注册表与默认角色矩阵单元测试。

期望值独立录入自 docs/PERMISSIONS.md 第 4 节（38 项 code）与第 5 节（五列矩阵），
不从被测映射复制，避免"自我相等"式伪验证。本批只测纯策略，不触库。
"""

from __future__ import annotations

import pytest
from app.core.permissions import PermissionCode, RoleCode
from app.modules.identity.policy import (
    DEFAULT_ROLE_PERMISSIONS,
    OPTIONAL_PERMISSION_CODES,
    can_change_roles,
)

# PERMISSIONS.md 第 5 节：逐列抄录每个"是"（"可选"/"条件派生"/"否"/"自动"不计入默认）。
_EXPECTED_SUPER_ADMIN = frozenset({
    "account.read", "account.manage", "role.assign",
    "optional_permission.manage", "identity.binding.manage",
    "academic.read", "academic.manage", "student.read", "student.manage",
    "volunteer.read", "volunteer.manage", "import.execute",
    "inspection.read", "inspection.generate", "inspection.cancel",
    "inspection.roster.read", "inspection.roster.manage",
    "assignment.manage", "assignment.change_review",
    "submission_deadline.read", "submission_deadline.manage",
    "submission.read", "submission.review",
    "attendance.expected_count_adjust", "attendance.read", "attendance.correct",
    "statistics.read", "report.read", "report.generate",
    "objection.read", "objection.initial_review", "objection.final_review",
    "audit.read", "system.config.read", "system.config.manage",
})
_EXPECTED_TEACHER_ADMIN = frozenset({
    "role.assign", "optional_permission.manage", "identity.binding.manage",
    "academic.read", "academic.manage", "student.read", "student.manage",
    "volunteer.read", "volunteer.manage", "import.execute",
    "inspection.read", "inspection.generate", "inspection.cancel",
    "inspection.roster.read", "inspection.roster.manage",
    "assignment.manage", "assignment.change_review",
    "submission_deadline.read", "submission_deadline.manage",
    "submission.read", "submission.review",
    "attendance.expected_count_adjust", "attendance.read", "attendance.correct",
    "statistics.read", "report.read", "report.generate",
    "objection.read", "objection.initial_review", "objection.final_review",
})
_EXPECTED_STUDENT_AFFAIRS_MANAGER = frozenset({
    "identity.binding.manage", "student.read", "inspection.read",
    "inspection.roster.read", "submission_deadline.read", "attendance.read",
})
_EXPECTED_VOLUNTEER = frozenset({
    "inspection.read", "inspection.roster.read", "assignment.change_request",
    "submission.create", "submission.read",
})
_EXPECTED_STUDENT = frozenset({
    "attendance.read", "objection.create", "objection.read",
})

_ALL_CODES = {p.value for p in PermissionCode}


def test_registry_is_exactly_38_and_excludes_assignment_read() -> None:
    assert len(PermissionCode) == 38
    assert "assignment.read" not in _ALL_CODES


def test_registry_member_values_match_baseline() -> None:
    # 抽样核对第 4 节点名的确切字符串，防手误。
    assert PermissionCode.ATTENDANCE_EXPECTED_COUNT_ADJUST.value == (
        "attendance.expected_count_adjust"
    )
    assert PermissionCode.OPTIONAL_PERMISSION_MANAGE.value == (
        "optional_permission.manage"
    )
    assert PermissionCode.IDENTITY_BINDING_MANAGE.value == "identity.binding.manage"
    # 三个既有成员名保持不变。
    assert PermissionCode.STATISTICS_READ.value == "statistics.read"
    assert PermissionCode.OBJECTION_INITIAL_REVIEW.value == "objection.initial_review"
    assert PermissionCode.REPORT_READ.value == "report.read"


def test_registry_and_manager_defaults() -> None:
    assert set(DEFAULT_ROLE_PERMISSIONS) == {r.value for r in RoleCode}
    assert DEFAULT_ROLE_PERMISSIONS["STUDENT_AFFAIRS_MANAGER"] == frozenset({
        "identity.binding.manage", "student.read", "inspection.read",
        "inspection.roster.read", "submission_deadline.read", "attendance.read",
    })
    assert frozenset({
        "statistics.read", "report.read", "objection.initial_review",
    }) == OPTIONAL_PERMISSION_CODES
    for codes in DEFAULT_ROLE_PERMISSIONS.values():
        assert codes <= _ALL_CODES


def test_default_matrix_matches_transcribed_expectations() -> None:
    assert DEFAULT_ROLE_PERMISSIONS[RoleCode.SUPER_ADMIN.value] == _EXPECTED_SUPER_ADMIN
    assert DEFAULT_ROLE_PERMISSIONS[RoleCode.TEACHER_ADMIN.value] == _EXPECTED_TEACHER_ADMIN
    assert (
        DEFAULT_ROLE_PERMISSIONS[RoleCode.STUDENT_AFFAIRS_MANAGER.value]
        == _EXPECTED_STUDENT_AFFAIRS_MANAGER
    )
    assert DEFAULT_ROLE_PERMISSIONS[RoleCode.VOLUNTEER.value] == _EXPECTED_VOLUNTEER
    assert DEFAULT_ROLE_PERMISSIONS[RoleCode.STUDENT.value] == _EXPECTED_STUDENT


def test_admin_has_no_automatic_actor_permissions() -> None:
    for role in ("SUPER_ADMIN", "TEACHER_ADMIN"):
        assert not DEFAULT_ROLE_PERMISSIONS[role] & {
            "submission.create", "assignment.change_request", "objection.create",
        }


@pytest.mark.parametrize(
    ("actor", "current", "desired", "expected"),
    [
        # 计划给定基线
        ({"TEACHER_ADMIN"}, set(), {"TEACHER_ADMIN"}, False),
        ({"TEACHER_ADMIN"}, {"TEACHER_ADMIN"}, set(), False),
        ({"TEACHER_ADMIN"}, set(), {"STUDENT_AFFAIRS_MANAGER"}, True),
        ({"TEACHER_ADMIN"}, {"STUDENT_AFFAIRS_MANAGER"}, set(), True),
        ({"SUPER_ADMIN"}, set(), {"TEACHER_ADMIN"}, True),
        ({"SUPER_ADMIN"}, {"TEACHER_ADMIN"}, set(), True),
        ({"SUPER_ADMIN"}, set(), {"VOLUNTEER"}, False),
        ({"TEACHER_ADMIN"}, {"STUDENT"}, {"STUDENT", "STUDENT_AFFAIRS_MANAGER"}, True),
        ({"TEACHER_ADMIN"}, {"STUDENT"}, {"STUDENT_AFFAIRS_MANAGER"}, False),
        # 补充：教师提交完整集合省略原有受保护教师角色 → 整体拒绝
        (
            {"TEACHER_ADMIN"},
            {"TEACHER_ADMIN", "STUDENT_AFFAIRS_MANAGER"},
            {"STUDENT_AFFAIRS_MANAGER"},
            False,
        ),
        # 补充：教师试图撤销目标已有 SUPER_ADMIN → 拒绝
        ({"TEACHER_ADMIN"}, {"SUPER_ADMIN", "STUDENT"}, {"STUDENT"}, False),
        # 补充：无任何管理角色者请求变更 → 拒绝
        ({"STUDENT"}, set(), {"STUDENT_AFFAIRS_MANAGER"}, False),
        # 补充：无变化请求（教师）→ 允许（空差集不触碰受保护角色）
        ({"TEACHER_ADMIN"}, {"STUDENT_AFFAIRS_MANAGER"}, {"STUDENT_AFFAIRS_MANAGER"}, True),
        # 补充：未知 code（期望集 / 现状集）→ 拒绝
        ({"TEACHER_ADMIN"}, set(), {"NOT_A_ROLE"}, False),
        ({"SUPER_ADMIN"}, {"GHOST_ROLE"}, set(), False),
        # 补充：合法+非法混合（教师加 SAM 同时加 TEACHER_ADMIN）→ 拒绝
        (
            {"TEACHER_ADMIN"},
            set(),
            {"STUDENT_AFFAIRS_MANAGER", "TEACHER_ADMIN"},
            False,
        ),
        # 补充：超管也不能旁路手工授予 VOLUNTEER（防旁路）→ 拒绝
        (
            {"SUPER_ADMIN"},
            set(),
            {"STUDENT_AFFAIRS_MANAGER", "VOLUNTEER"},
            False,
        ),
        # 补充：超管合法（保留 STUDENT，仅加 TEACHER_ADMIN）→ 允许
        ({"SUPER_ADMIN"}, {"STUDENT"}, {"STUDENT", "TEACHER_ADMIN"}, True),
    ],
)
def test_role_change_boundary(
    actor: set[str], current: set[str], desired: set[str], expected: bool
) -> None:
    assert can_change_roles(
        frozenset(actor), frozenset(current), frozenset(desired),
    ) is expected
