"""基础数据模块权限与业务规则（纯判断，无数据库访问）。

来源：docs/PERMISSIONS.md 第 4.2、7 节与第 12 节导入复合权限矩阵。

- 资源→权限映射沿用集中 code（academic/student/volunteer 的 read/manage），
  本模块只补充"导入 = import.execute + 目标资源 manage"的复合要求，以及若干
  跨表共享的取值常量（记录状态、导入目标枚举）。
- 数据范围：PERMISSIONS.md 第 7 节把范围判定下放到模块自身。V1.0 基础数据以
  学院（college）为业务边界，但账号↔学院绑定尚未在身份模型落地，故列表查询提供
  可选 `college` 过滤参数（由具备管理权限者自行按学院收窄），不做跨校/跨租户通配，
  也不臆造学校制度数值。待身份模型补充学院归属后，此处收敛为强制行级过滤。
"""

from __future__ import annotations

from app.core.permissions import PermissionCode

# 记录启停状态（行政班/学生/课程/教学班/课表通用）。语义与 CHECK/服务守卫一致。
RECORD_STATUS_ACTIVE = "ACTIVE"
RECORD_STATUS_DISABLED = "DISABLED"
ALLOWED_RECORD_STATUS: frozenset[str] = frozenset({RECORD_STATUS_ACTIVE, RECORD_STATUS_DISABLED})

# 学期状态：仅 ACTIVE 可写业务数据；ARCHIVED 只读历史。
SEMESTER_STATUS_ACTIVE = "ACTIVE"
SEMESTER_STATUS_ARCHIVED = "ARCHIVED"
ALLOWED_SEMESTER_STATUS: frozenset[str] = frozenset(
    {SEMESTER_STATUS_ACTIVE, SEMESTER_STATUS_ARCHIVED}
)

# 校历覆盖类型（与模型 CHECK 一致）。
OVERRIDE_STOP = "STOP"
OVERRIDE_MAKEUP = "MAKEUP"
ALLOWED_OVERRIDE_TYPE: frozenset[str] = frozenset({OVERRIDE_STOP, OVERRIDE_MAKEUP})

# 导入目标 → 复合权限：import.execute + 目标资源 manage（PERMISSIONS.md 第 12 节）。
# 键为稳定的导入类型码，值为“除 import.execute 外还须具备的管理权限”。
IMPORT_TARGET_PERMISSIONS: dict[str, str] = {
    "roster": PermissionCode.STUDENT_MANAGE.value,  # 学生/教学班名单
    "timetable": PermissionCode.ACADEMIC_MANAGE.value,  # 课表/教学班基础信息
    "volunteer": PermissionCode.VOLUNTEER_MANAGE.value,  # 志愿者学期资格
}
IMPORT_TARGETS: frozenset[str] = frozenset(IMPORT_TARGET_PERMISSIONS)


def import_required_permissions(target: str) -> tuple[str, ...]:
    """返回执行某类导入所需的全部权限 code（import.execute + 目标 manage）。

    未知 target 抛 ValueError，由上层映射为 422（防御性：路由/服务应先校验 target 合法）。
    """
    if target not in IMPORT_TARGET_PERMISSIONS:
        raise ValueError(f"未知导入目标类型：{target}")
    return (PermissionCode.IMPORT_EXECUTE.value, IMPORT_TARGET_PERMISSIONS[target])
