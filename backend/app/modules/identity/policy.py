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
#
# 志愿者继承学生基础权限（PERMISSIONS.md §1.5 "VOLUNTEER 自动继承 STUDENT 全部基础权限"）
# 不在此表内以静态并集表达——原因：绑定成功后 bind_student 必发 STUDENT 角色；志愿者资格
# 生效时 importer / bind_student 反向补授 VOLUNTEER，所以一个"合法志愿者"必然同时持有
# STUDENT + VOLUNTEER 两个角色，Repository.list_effective_permissions 取角色权限并集，
# 学生基础三项（attendance.read / objection.create / objection.read）自然到位。
# 反之 student_binding_reset 解绑会收回 STUDENT 但保留 VOLUNTEER（历史只读入口），若把这三项
# 硬写进 VOLUNTEER 集，绑定失效者仍能通过继承门禁访问学生数据，违反 §1.5 "未绑定、绑定失效
# 或账号停用不得借继承绕过限制"。因此 VOLUNTEER 集刻意不含这三项，由"绑定同持 STUDENT"的
# 不变量提供继承能力；契约钉死见 tests/integration/test_importer.py 中
# test_volunteer_inherits_student_base_via_bound_student_role_union。
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
    # VOLUNTEER：仅志愿者专有语义权限；学生基础三项经"绑定同持 STUDENT"并集获得，见上方注释。
    RoleCode.VOLUNTEER.value: frozenset({
        "inspection.read",
        "inspection.roster.read",
        "assignment.change_request",
        "submission.create",
        "submission.read",
    }),
    # STUDENT：绑定即获得；解绑即收回；三项基础权限是 VOLUNTEER 继承能力的来源。
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
