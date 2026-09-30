"""失效受派允许留存多条历史，同时数据库只容许一个当前受派。"""

from app.modules.inspection.models import InspectionAssignment
from sqlalchemy import UniqueConstraint


def test_assignment_active_generated_key_and_unique_constraint() -> None:
    table = InspectionAssignment.__table__
    assert table.c.revoked_at.nullable
    assert table.c.active_task_id.computed is not None
    assert table.c.active_task_id.computed.persisted is True
    assert "revoked_at" in str(table.c.active_task_id.computed.sqltext)
    assert any(
        isinstance(item, UniqueConstraint)
        and [column.name for column in item.columns] == ["active_task_id"]
        for item in table.constraints
    )
    assert not any(
        isinstance(item, UniqueConstraint)
        and [column.name for column in item.columns] == ["task_id"]
        for item in table.constraints
    )
