"""ORM 模型聚合导入入口。

Alembic 的 target_metadata 通过导入本模块收集所有表的统一 metadata。
**每新增一个 models.py，必须在此显式导入其模型类**，否则 autogenerate 检测不到变更。
示例：

    from app.modules.academic import models as academic_models  # noqa: F401
    from app.modules.identity import models as identity_models  # noqa: F401

阶段 1 起按技术方案第 9 节逐步补齐各模块表映射（采用 DeclarativeBase +
Mapped + mapped_column 风格，枚举以字符串值存储）。当前为空骨架。
"""

from __future__ import annotations

from app.core.database import Base

# 导入即注册到 Base.metadata。新增 models.py 必须在此登记，否则 autogenerate 检测不到。
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401

__all__ = ["Base"]
