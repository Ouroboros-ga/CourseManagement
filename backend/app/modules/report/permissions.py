"""统计/周报域权限与数据范围判定（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 4.5、5、6.2、7 节与技术方案第 17、18 节。

职责边界（与 attendance/objection/permissions.py 一致）：
- 功能权限 code 用集中 `PermissionCode`（statistics.read / report.read / report.generate），
  路由层 `require_permission` 早拦、服务层事务内重读有效权限纵深复核，本模块不重复守卫；
- 本模块只落地"谁能看统计/周报"这一数据范围维度；统计与周报皆为聚合读数，
  V1.0 尚未落地账号↔学院归属，管理类全量可见、非管理类拒绝（沿用 academic/inspection/
  attendance 一致处理，补齐学院归属后收敛为强制行级过滤）。

三权分立的关键约束（PERMISSIONS.md 第 266 行）：
- `statistics.read`、`report.read` 属逐人开关的可选项（默认关闭），`report.generate` 非可选；
- 周报下载含个人明细，statistics.read **不得**隐式取得 report.read；二者独立判定，
  故本模块不提供"有统计即可读周报"的任何捷径。
"""

from __future__ import annotations

import enum

from app.core.permissions import PermissionCode, RoleCode

# 功能权限 code（矩阵 PERMISSIONS.md 第 254–256 行）。
STATISTICS_READ_PERMISSION = PermissionCode.STATISTICS_READ.value
REPORT_READ_PERMISSION = PermissionCode.REPORT_READ.value
REPORT_GENERATE_PERMISSION = PermissionCode.REPORT_GENERATE.value


class ReportScope(enum.StrEnum):
    """统计/周报读取范围（聚合读数无"本人"维度，仅有管理全量与拒绝两态）。

    统计与周报都是跨学生的聚合指标，不适用 attendance/objection 的"本人行级"语义；
    因此非管理类角色即便被误授统计可读，也不存在"缩小到本人"的中间态——要么管理全量，
    要么在功能守卫阶段即被拒（403）。保留枚举是为与其余模块 permissions 形态一致，
    并为后续学院级行过滤预留收敛位。
    """

    MANAGE = "MANAGE"  # 管理类：全量聚合可见
    DENIED = "DENIED"  # 其余：无聚合读数入口（功能守卫本应先拦，此处纵深兜底）


_MANAGE_ROLES: frozenset[str] = frozenset(
    {
        RoleCode.SUPER_ADMIN.value,
        RoleCode.TEACHER_ADMIN.value,
        RoleCode.STUDENT_AFFAIRS_MANAGER.value,
    }
)


def resolve_read_scope(roles: list[str]) -> ReportScope:
    """依角色集合解析统计/周报读取范围（管理类→MANAGE，其余→DENIED）。

    注意：这只解析"范围"，不替代功能权限守卫——是否 *可* 读仍由持有 statistics.read /
    report.read 决定。二者叠加效果：非管理角色即使被授予可选 statistics.read，其范围仍为
    DENIED（聚合读数无本人子集可缩），实现处以 MANAGE 为准入门槛。
    """
    if set(roles) & _MANAGE_ROLES:
        return ReportScope.MANAGE
    return ReportScope.DENIED


def is_manage_scope(scope: ReportScope) -> bool:
    """该范围是否可读取全量聚合。"""
    return scope is ReportScope.MANAGE


__all__ = [
    "STATISTICS_READ_PERMISSION",
    "REPORT_READ_PERMISSION",
    "REPORT_GENERATE_PERMISSION",
    "ReportScope",
    "resolve_read_scope",
    "is_manage_scope",
]
