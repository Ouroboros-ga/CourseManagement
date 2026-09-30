"""排班读快照不能向持锁请求的单连接池再次借连接。"""

from types import SimpleNamespace

from app.modules.inspection.schemas import AutoAssignRequest
from app.modules.inspection.service import InspectionService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool


def test_empty_auto_scope_uses_fresh_reader_without_exhausting_writer_pool(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=QueuePool,
                           pool_size=1, max_overflow=0, pool_timeout=0.1)
    try:
        with Session(engine) as writer:
            service = InspectionService(writer)

            def checked_permission(self, *_):
                # 持有写 Session 的唯一物理连接。
                self._session.execute(text("SELECT 1"))

            def read_empty_scope(self, *_):
                # 快照 Session 必须真实取连接，测试不能只检查构造函数。
                self._session.execute(text("SELECT 1"))
                return []

            def candidate_lookup_must_not_run(self, *_):
                raise AssertionError("空任务范围不应再查志愿者")

            monkeypatch.setattr(InspectionService, "_require", checked_permission)
            monkeypatch.setattr(InspectionService, "_load_assign_targets", read_empty_scope)
            monkeypatch.setattr(InspectionService, "_active_volunteer_user_ids",
                                candidate_lookup_must_not_run)
            service._academic = SimpleNamespace(get_semester_for_update=lambda _: SimpleNamespace(
                id=1, status="ACTIVE"))
            result = service.auto_assign(SimpleNamespace(id=1),
                                         AutoAssignRequest(semester_id=1, task_ids=[1]), None)
            assert result.target_task_count == 0
            assert not result.assigned
    finally:
        engine.dispose()
