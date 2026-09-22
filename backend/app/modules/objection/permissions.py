"""异议域权限与数据范围判定（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 5、7.6、8 节，技术方案第 14 节。

职责边界（与 attendance/inspection/permissions.py 一致）：
- 功能权限 code 用集中 `PermissionCode`（objection.create / read / initial_review /
  final_review，外加终审更正所需的 attendance.correct），路由层早拦、服务层事务内重读有效
  权限纵深复核，本模块不重复守卫；
- 本模块只落地"谁能读/能处理哪些异议"这一数据范围维度，范围谓词的实际 SQL 由 service 构造。

关键差异（相对考勤）——异议读取的"管理路径"不是靠 objection.read：
- 超级管理员 / 教师管理员：矩阵直授 objection.read、objection.initial_review、
  objection.final_review，管理全学院异议（PERMISSIONS.md 8.3）；
- 学生工作负责人：默认**不持** objection.read（矩阵"条件派生"），只有被授予可选项
  objection.initial_review 后，才**派生**出"读取全学院异议 + 初核"的管理路径
  （PERMISSIONS.md 8.2）；关闭初核即失去该读取来源，attendance.read 不提供替代的证明读取权；
- 志愿者 / 学生：仅本人异议（objection.read + OWN_OBJECTION，志愿者经"绑定同持 STUDENT"
  的角色并集继承 objection.read / objection.create，非静态写进 VOLUNTEER 集）。

故管理读取路径判定 = 持有 objection.initial_review 或 objection.final_review 之一；
本人读取路径判定 = 持有 objection.read 且有有效 student_id 绑定。二者皆无 → 无读取路径。
"""

from __future__ import annotations

import enum

from app.core.permissions import PermissionCode


class ObjectionScope(enum.StrEnum):
    MANAGE = "MANAGE"  # 管理路径：全学院异议可读 / 可初核 / 可终审
    OWN = "OWN"  # 本人路径：仅 objection.student_id == 本人 student_id
    NONE = "NONE"  # 无任何异议读取路径


# 功能权限 code（集中注册表，供路由守卫与服务纵深）。
OBJECTION_CREATE_PERMISSION = PermissionCode.OBJECTION_CREATE.value
OBJECTION_READ_PERMISSION = PermissionCode.OBJECTION_READ.value
OBJECTION_INITIAL_REVIEW_PERMISSION = PermissionCode.OBJECTION_INITIAL_REVIEW.value
OBJECTION_FINAL_REVIEW_PERMISSION = PermissionCode.OBJECTION_FINAL_REVIEW.value
# 终审通过且需更正考勤时额外要求（PERMISSIONS.md 758：final_review AND attendance.correct）。
ATTENDANCE_CORRECT_PERMISSION = PermissionCode.ATTENDANCE_CORRECT.value

# 构成"管理异议读取路径"的权限：持其一即获全学院读取（PERMISSIONS.md 8.2/8.3）。
MANAGE_READ_PERMISSIONS: frozenset[str] = frozenset(
    {OBJECTION_INITIAL_REVIEW_PERMISSION, OBJECTION_FINAL_REVIEW_PERMISSION}
)


def resolve_read_scope(permissions: set[str]) -> ObjectionScope:
    """依操作者有效权限判定异议读取范围（管理路径优先于本人路径）。

    注意：本函数只判"权限层面"的范围；本人路径还要求服务层能解析出有效 student_id，
    无 student_id 者即便持 objection.read 也应在服务层降级为 NONE（不退化为无范围查询）。
    """
    if permissions & MANAGE_READ_PERMISSIONS:
        return ObjectionScope.MANAGE
    if OBJECTION_READ_PERMISSION in permissions:
        return ObjectionScope.OWN
    return ObjectionScope.NONE


def is_manage_scope(scope: ObjectionScope) -> bool:
    return scope is ObjectionScope.MANAGE


def may_initial_review(permissions: set[str]) -> bool:
    """是否具备初核权限（决定读取范围外的动作能力，非读取判定）。"""
    return OBJECTION_INITIAL_REVIEW_PERMISSION in permissions


def may_final_review(permissions: set[str]) -> bool:
    return OBJECTION_FINAL_REVIEW_PERMISSION in permissions


__all__ = [
    "ObjectionScope",
    "OBJECTION_CREATE_PERMISSION",
    "OBJECTION_READ_PERMISSION",
    "OBJECTION_INITIAL_REVIEW_PERMISSION",
    "OBJECTION_FINAL_REVIEW_PERMISSION",
    "ATTENDANCE_CORRECT_PERMISSION",
    "MANAGE_READ_PERMISSIONS",
    "resolve_read_scope",
    "is_manage_scope",
    "may_initial_review",
    "may_final_review",
]
