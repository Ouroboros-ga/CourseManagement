"""考勤域权限与数据范围判定（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 4.4、7.1、7.2、7.3、12.8 节与技术方案第 14 节。

职责边界（与 inspection/permissions.py 一致）：
- 功能权限 code 用集中 `PermissionCode`（attendance.read / attendance.correct），
  路由层 `require_permission` 早拦、服务层事务内重读有效权限纵深复核，本模块不重复守卫；
- 本模块只落地"谁能看见/改哪些考勤"这一数据范围维度，范围谓词的实际 SQL 由 service 构造。

数据范围（PERMISSIONS.md 7）：
- 管理范围（SYSTEM_WIDE / ALL_GRADES）：超级管理员、教师管理员、学生工作负责人——
  可读全部当前考勤与历史认定（V1.0 学院↔账号归属尚未落地，负责人与超管同样全量可见，
  沿用 academic/inspection 一致处理，待补齐后收敛为强制行级过滤）；
- 本人范围（SELF_STUDENT）：志愿者（继承学生）、普通学生——仅可读取
  resource.student_id == 本人 student_id 的考勤；未绑定 student_id 直接拒绝，
  不退化为无范围查询（PERMISSIONS.md 7.3）。

更正（attendance.correct）：仅超级管理员、教师管理员（PERMISSIONS.md 388、技术方案 14），
负责人/志愿者/学生皆无；负责人关闭终审批照后仍不得更正最终考勤。范围判定不涉更正权限，
更正的鉴权完全由功能 code 承担，故本模块不提供"可更正范围"谓词——凡持 correct 者即可
对任意记录在版本一致前提下更正。

多角色并集：志愿者绑定同持 STUDENT+VOLUNTEER，均落到 SELF_STUDENT；管理角色优先，
判定顺序为"管理范围 > 本人范围"，避免管理者被误判为仅本人可见。既无管理角色又非绑定
学生者本就不具备 attendance.read，被功能守卫在到达此处前拦下。
"""

from __future__ import annotations

import enum

from app.core.permissions import PermissionCode, RoleCode


class AttendanceScope(enum.StrEnum):
    MANAGE = "MANAGE"  # 管理范围：全部考勤可见
    SELF_STUDENT = "SELF_STUDENT"  # 本人范围：仅 student_id 命中的记录


# 考勤读取所需功能权限（矩阵 387：五角色皆可，志愿者/学生为继承且仅本人）。
ATTENDANCE_READ_PERMISSION = PermissionCode.ATTENDANCE_READ.value
# 考勤更正所需功能权限（矩阵 388：仅超管、教师管理员）。
ATTENDANCE_CORRECT_PERMISSION = PermissionCode.ATTENDANCE_CORRECT.value


def resolve_read_scope(roles: list[str]) -> AttendanceScope:
    """依角色集合解析考勤读取数据范围（管理范围优先于本人范围）。"""
    role_set = set(roles)
    if (
        RoleCode.SUPER_ADMIN.value in role_set
        or RoleCode.TEACHER_ADMIN.value in role_set
        or RoleCode.STUDENT_AFFAIRS_MANAGER.value in role_set
    ):
        return AttendanceScope.MANAGE
    # 志愿者 / 学生（及任何却持 attendance.read 的非管理者）：仅本人。
    return AttendanceScope.SELF_STUDENT


def is_manage_scope(scope: AttendanceScope) -> bool:
    """该范围是否可跨学生查看全部考勤。"""
    return scope is AttendanceScope.MANAGE


__all__ = [
    "AttendanceScope",
    "ATTENDANCE_READ_PERMISSION",
    "ATTENDANCE_CORRECT_PERMISSION",
    "resolve_read_scope",
    "is_manage_scope",
]
