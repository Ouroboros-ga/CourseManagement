"""身份模块权限策略：默认角色权限矩阵与角色变更边界（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 5 节（默认矩阵）与第 6 节（角色授权边界）。
本模块是默认值的唯一真相源，种子与授权服务必须复用同一映射，禁止另立默认集合。
集合减法仅用于表达显式矩阵，不代表超管在运行时绕过资源范围/状态/版本等业务守卫。
"""

from __future__ import annotations

from app.core.permissions import PermissionCode, RoleCode

# 逐人开关的可选项，默认不随任何角色授予（PERMISSIONS.md 6.2）。
OPTIONAL_PERMISSION_CODES: frozenset[str] = frozenset({
    "statistics.read",
    "report.read",
    "objection.initial_review",
})

# 超管基线：全部权限减去三项"执行者身份"权限——
# 超级管理员不因角色身份自动获得代志愿者提交或代学生提异议的业务身份。
_admin: frozenset[str] = frozenset(p.value for p in PermissionCode) - {
    "assignment.change_request",
    "submission.create",
    "objection.create",
}

# 默认角色 → 权限 code 集合（PERMISSIONS.md 第 5 节的"是"；可选/条件派生/自动不计入）。
DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    RoleCode.SUPER_ADMIN.value: _admin,
    RoleCode.TEACHER_ADMIN.value: _admin - {
        "account.read",
        "account.manage",
        "audit.read",
        "system.config.read",
        "system.config.manage",
    },
    RoleCode.STUDENT_AFFAIRS_MANAGER.value: frozenset({
        "identity.binding.manage",
        "student.read",
        "inspection.read",
        "inspection.roster.read",
        "submission_deadline.read",
        "attendance.read",
    }),
    RoleCode.VOLUNTEER.value: frozenset({
        "inspection.read",
        "inspection.roster.read",
        "assignment.change_request",
        "submission.create",
        "submission.read",
    }),
    RoleCode.STUDENT.value: frozenset({
        "attendance.read",
        "objection.create",
        "objection.read",
    }),
}


def can_change_roles(
    actor_roles: frozenset[str],
    current_roles: frozenset[str],
    desired_roles: frozenset[str],
) -> bool:
    """仅判定角色类型边界（PERMISSIONS.md 第 6 节），不判定学院范围或 Permission。

    - 任一集合含未知 code → False（API schema 另映射为 422）。
    - 差集触及 STUDENT / VOLUNTEER（业务身份自动维护）→ False，超管亦不可旁路。
    - 持 SUPER_ADMIN：其余变更全部允许。
    - 仅持 TEACHER_ADMIN：差集只能是 STUDENT_AFFAIRS_MANAGER 的增删。
    - 无管理角色：False。
    自身与他人为同一边界，故不需要 user_id；自我可选权限提权由管理服务单独拦截。
    """
    known = frozenset(r.value for r in RoleCode)
    if not (actor_roles | current_roles | desired_roles) <= known:
        return False
    changed = current_roles ^ desired_roles
    if changed & {"STUDENT", "VOLUNTEER"}:
        return False
    if "SUPER_ADMIN" in actor_roles:
        return True
    if "TEACHER_ADMIN" in actor_roles:
        return changed <= {"STUDENT_AFFAIRS_MANAGER"}
    return False


def assignable_roles(actor_roles: frozenset[str]) -> list[str]:
    """该操作者可授予他人的角色集合（供受限目标选择器展示"可操作角色"）。

    复用 can_change_roles 作为唯一真相源：对每个已知角色，判断在空角色目标上
    单独新增它是否被允许。STUDENT/VOLUNTEER 属业务身份自动维护，恒不入选。
    """
    return sorted(
        code
        for code in (r.value for r in RoleCode)
        if can_change_roles(actor_roles, frozenset(), frozenset({code}))
    )
