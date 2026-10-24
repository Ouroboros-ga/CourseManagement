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
from app.modules.agent import models as agent_models  # noqa: F401
from app.modules.academic import campus_models as campus_academic_models  # noqa: F401
from app.modules.academic import enrollment_models  # noqa: F401

# 导入即注册到 Base.metadata。新增 models.py 必须在此登记，否则 autogenerate 检测不到。
from app.modules.academic import models as academic_models  # noqa: F401
from app.modules.academic import occurrence_location_models  # noqa: F401
from app.modules.academic import publication_models as publication_models  # noqa: F401
from app.modules.academic import offering_models  # noqa: F401
from app.modules.academic import school_time_models as school_time_models  # noqa: F401
from app.modules.academic import time_models as time_models  # noqa: F401
from app.modules.academic import staff_models as staff_models  # noqa: F401
from app.modules.attendance import models as attendance_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.file import models as file_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.identity import staff_binding_models as staff_binding_models  # noqa: F401
from app.modules.importer import models as importer_models  # noqa: F401
from app.modules.inspection import assignment_plan_models  # noqa: F401
from app.modules.inspection import automation_models  # noqa: F401
from app.modules.inspection import models as inspection_models  # noqa: F401
from app.modules.inspection import responsibility  # noqa: F401
from app.modules.objection import models as objection_models  # noqa: F401
from app.modules.objection import precheck_models  # noqa: F401
from app.modules.organization import impact_models  # noqa: F401
from app.modules.organization import models as organization_models  # noqa: F401
from app.modules.report import models as report_models  # noqa: F401
from app.modules.timetable import models as timetable_models  # noqa: F401
from app.modules.volunteer import member_models as volunteer_member_models  # noqa: F401
from app.modules.volunteer import models as volunteer_models  # noqa: F401
from app.modules.volunteer import preparation_models  # noqa: F401
from app.modules.volunteer import unavailability_models  # noqa: F401

__all__ = ["Base"]
