"""仅清理没有业务引用的组及其配置；业务历史由外键引用守卫保留。"""

from sqlalchemy import delete, select

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.modules.volunteer.models import GroupConfigVersion, GroupScopeType


def remove_unused_group_configuration(db, group):
    versions = list(
        db.scalars(
            select(GroupConfigVersion.id)
            .where(GroupConfigVersion.group_id == group.id)
            .with_for_update()
        )
    )
    owned = {"group_config_version", "group_scope_type"}
    # 包括成员、支援、学期准备、任务及负责人专属授权；新引用表也自动受保护。
    for table in Base.metadata.sorted_tables:
        if table.name in owned:
            continue
        for fk in table.foreign_keys:
            if fk.column.name != "id":
                continue
            if fk.column.table.name == "volunteer_group":
                condition = fk.parent == group.id
            elif fk.column.table.name == "group_config_version" and versions:
                condition = fk.parent.in_(versions)
            else:
                continue
            if db.execute(select(fk.parent).where(condition).limit(1)).first() is not None:
                raise ConflictError(
                    message=(
                        "该组已有成员、任务、学期准备或授权记录，请先处置关联；"
                        "历史记录仍保留，可停用该组"
                    )
                )
    if versions:
        db.execute(delete(GroupScopeType).where(GroupScopeType.config_id.in_(versions)))
        db.execute(delete(GroupConfigVersion).where(GroupConfigVersion.id.in_(versions)))
