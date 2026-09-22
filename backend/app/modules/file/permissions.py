"""文件模块的上传/访问权限判定（技术方案 16.1、16.2；PERMISSIONS.md）。

文件不设独立功能权限 code——它随"用途"授权：上传哪种类别的材料，要求操作者具备使用
该类材料的业务权限；访问已关联的文件，按其所挂业务资源的归属授权（技术方案 16.2
"校验身份、功能及业务资源归属"）。本模块只落地纯判定，DB 侧的归属联表在 repository。

上传类别 → 所需最低权限（None 表示任何已完成绑定的登录用户即可上传，用于志愿者
本人提交照片 / 学生本人异议证明——真正的越权门禁在关联与访问时按资源归属再判）。
"""

from __future__ import annotations

from app.core.permissions import PermissionCode

# 客户端可上传的材料类别（导入原始文件走 importer 通道，不经此端点）。
UPLOADABLE_CATEGORIES: frozenset[str] = frozenset(
    {"SUBMISSION_PHOTO", "OBJECTION_PROOF", "TEMP"}
)

# 类别 → 上传所需的额外功能权限；缺省即无（仅需绑定完成）。
CATEGORY_UPLOAD_EXTRA_PERMISSION: dict[str, str] = {
    # 周报/审计类材料不由普通客户端上传；保留映射位供后续收紧。
    "REPORT_FILE": PermissionCode.REPORT_GENERATE.value,
}


def is_uploadable_category(category: str) -> bool:
    return category in UPLOADABLE_CATEGORIES


def required_upload_permission(category: str) -> str | None:
    """该上传类别是否额外要求某功能权限（None = 仅需绑定完成）。"""
    return CATEGORY_UPLOAD_EXTRA_PERMISSION.get(category)


__all__ = [
    "UPLOADABLE_CATEGORIES",
    "CATEGORY_UPLOAD_EXTRA_PERMISSION",
    "is_uploadable_category",
    "required_upload_permission",
]
