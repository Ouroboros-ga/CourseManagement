"""查课任务与排班模块的权限与数据范围判定（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 4.3、5、7、12.6 节与技术方案第 11 节。

职责边界：
- 功能权限 code 用集中 `PermissionCode`（inspection.read / generate / cancel /
  roster.read / assignment.manage / submission_deadline.* 等），路由层 `require_permission`
  早拦、服务层事务内重读有效权限纵深复核，本模块不重复守卫本身；
- 本模块只落地"数据范围"这一维度：谁能看见哪些任务。范围谓词的实际 SQL 由
  service 依此判定结果构造，使列表 / 详情 / 计数共用同一可见性条件（PERMISSIONS.md 7）。

数据范围（PERMISSIONS.md 7）：
- SYSTEM_WIDE：超级管理员、教师管理员——全部当前学期任务；
- ALL_GRADES：学生工作负责人——本学院全部年级任务、排班、截止时间（V1.0 学院↔账号
  归属尚未在身份模型落地，故与 SYSTEM_WIDE 同样可见全部，不做跨校通配，待补齐后收敛
  为强制行级过滤，沿用 academic 模块一致处理）；
- ASSIGNED_TASK：志愿者——仅本人当前受派任务（assignment.volunteer_user_id = 本人）。
  （OWN_SUBMISSION / SELF_STUDENT 只读范围随 P5/P6 提交、异议模块落地，本波不涉及。）

角色并集说明：绑定志愿者同时持有 STUDENT+VOLUNTEER；管理读取范围（SYSTEM_WIDE /
ALL_GRADES）优先于 ASSIGNED_TASK，故判定顺序为"管理范围 > 志愿者范围"，避免多角色
者被误判为仅本人可见。既无管理角色又非志愿者的账号本就不具备 inspection.read，
被功能守卫在到达此处前拦下，这里对未知角色保守回落到 ASSIGNED_TASK（最小可见）。
"""

from __future__ import annotations

import enum
from collections.abc import Sequence

from app.core.permissions import PermissionCode, RoleCode


class DataScope(enum.StrEnum):
    SYSTEM_WIDE = "SYSTEM_WIDE"
    ALL_GRADES = "ALL_GRADES"
    ASSIGNED_TASK = "ASSIGNED_TASK"


# 具备"管理类"全部可见的范围：SYSTEM_WIDE / ALL_GRADES（此时无学院分区，二者等价）。
MANAGEMENT_SCOPES: frozenset[DataScope] = frozenset(
    {DataScope.SYSTEM_WIDE, DataScope.ALL_GRADES}
)

# 允许生成的查课类型（与 inspection.models.InspectionType 的 CHECK 集合一致）。
ALLOWED_INSPECTION_TYPES: frozenset[str] = frozenset(
    {"COURSE", "MORNING_STUDY", "EVENING_STUDY"}
)
# 需以行政班 + 显式节次范围为对象、无课表来源的自习类型。
STUDY_TYPES: frozenset[str] = frozenset({"MORNING_STUDY", "EVENING_STUDY"})

# 生成 / 预览所需功能权限（复合：仅 inspection.generate 一项即可，技术方案 11.1）。
GENERATE_PERMISSION = PermissionCode.INSPECTION_GENERATE.value
READ_PERMISSION = PermissionCode.INSPECTION_READ.value
ROSTER_READ_PERMISSION = PermissionCode.INSPECTION_ROSTER_READ.value
CANCEL_PERMISSION = PermissionCode.INSPECTION_CANCEL.value
# 自动排班 / 人工改派所需功能权限（PERMISSIONS.md 4.3、12.6）。
ASSIGN_PERMISSION = PermissionCode.ASSIGNMENT_MANAGE.value
# Wave 3b 调班申请：志愿者发起/读取本人申请（PERMISSIONS.md 4.3、12.6）。
CHANGE_REQUEST_PERMISSION = PermissionCode.ASSIGNMENT_CHANGE_REQUEST.value
# Wave 3b 调班申请：管理人员读取/处理申请。
CHANGE_REVIEW_PERMISSION = PermissionCode.ASSIGNMENT_CHANGE_REVIEW.value
# Wave 3c：名单改版（执行前更正，生成新版本快照）。
ROSTER_MANAGE_PERMISSION = PermissionCode.INSPECTION_ROSTER_MANAGE.value
# Wave 3c：提交截止时间配置读取 / 管理。
DEADLINE_READ_PERMISSION = PermissionCode.SUBMISSION_DEADLINE_READ.value
DEADLINE_MANAGE_PERMISSION = PermissionCode.SUBMISSION_DEADLINE_MANAGE.value


def resolve_scope(roles: Sequence[str]) -> DataScope:
    """依角色集合解析任务读取数据范围（管理范围优先于本人受派范围）。"""
    role_set = set(roles)
    if RoleCode.SUPER_ADMIN.value in role_set or RoleCode.TEACHER_ADMIN.value in role_set:
        return DataScope.SYSTEM_WIDE
    if RoleCode.STUDENT_AFFAIRS_MANAGER.value in role_set:
        return DataScope.ALL_GRADES
    # 志愿者（及任何非管理角色却持有 inspection.read 的情形）保守最小可见：本人受派。
    return DataScope.ASSIGNED_TASK


def is_management_scope(scope: DataScope) -> bool:
    """该范围是否可见全部任务（用于详情/名单是否需再核对受派归属）。"""
    return scope in MANAGEMENT_SCOPES


__all__ = [
    "DataScope",
    "MANAGEMENT_SCOPES",
    "ALLOWED_INSPECTION_TYPES",
    "STUDY_TYPES",
    "GENERATE_PERMISSION",
    "READ_PERMISSION",
    "ROSTER_READ_PERMISSION",
    "CANCEL_PERMISSION",
    "ASSIGN_PERMISSION",
    "CHANGE_REQUEST_PERMISSION",
    "CHANGE_REVIEW_PERMISSION",
    "ROSTER_MANAGE_PERMISSION",
    "DEADLINE_READ_PERMISSION",
    "DEADLINE_MANAGE_PERMISSION",
    "resolve_scope",
    "is_management_scope",
]
