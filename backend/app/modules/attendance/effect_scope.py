"""撤回的考勤默认对业务查询隐身；只有历史、证据与级联清理路径显式放行。

机制是 Session 级 do_orm_execute 监听器，给每条 ORM 查询追加 with_loader_criteria。已实测
该条件覆盖本仓库用到的全部查询形状：实体查询、只选列、func.count().select_from()、由别的
实体 join 进来、IN 子查询、aliased()，以及 session.get()。所以新增读取路径无需记得加谓词，
默认就是"看不到已撤回的结论"。

放行用语句级 execution_options，必须加在交给 Session.execute 的最外层语句上——嵌套子查询不
会单独携带该选项。反过来，delete()/update() 不受本监听器影响，撤回操作才能改写这些行。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

#: 显式放行已撤回考勤行的语句级选项名。
INCLUDE_WITHDRAWN = "include_withdrawn_attendance"

_record_cls: Any = None
_effective_value: str = ""
_installed = False


def install(record_cls: Any, effective_value: str) -> None:
    """由 attendance.models 在定义完 AttendanceRecord 后调用，注册全局默认过滤。"""
    global _record_cls, _effective_value, _installed
    _record_cls = record_cls
    _effective_value = effective_value
    if not _installed:
        event.listen(Session, "do_orm_execute", _hide_withdrawn, propagate=True)
        _installed = True


def _hide_withdrawn(state: Any) -> None:
    if _record_cls is None or not state.is_select:
        return
    if state.execution_options.get(INCLUDE_WITHDRAWN):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            _record_cls,
            _record_cls.effect_state == _effective_value,
            include_aliases=True,
        )
    )


def see_withdrawn(statement: Any) -> Any:
    """读取全部考勤行（含已撤回）：历史可达、证据鉴权、级联清理与"是否已有考勤事实"守卫。"""
    return statement.execution_options(**{INCLUDE_WITHDRAWN: True})
