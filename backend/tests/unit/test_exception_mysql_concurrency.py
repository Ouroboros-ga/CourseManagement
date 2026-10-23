"""仅隔离 MySQL 验证相同任务写入互斥；本机 SQLite 明确跳过。"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.core.exceptions import AppError
from app.modules.attendance.models import AttendanceRecord
from app.modules.inspection.models import InspectionSubmission, InspectionTask
from app.modules.inspection.schemas import SubmissionCreateRequest, TaskCancelRequest
from app.modules.inspection.service import InspectionService
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.unit.test_task_exception import execution as execution_fixture
from tests.unit.test_task_exception import fixture as campus_fixture

pytestmark = pytest.mark.skipif(
    not os.environ.get("CAMPUS_TEST_DATABASE_URL"), reason="requires isolated MySQL row locks"
)


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


@pytest.fixture(name="execution")
def setup(campus, monkeypatch):
    return execution_fixture.__wrapped__(campus, monkeypatch)


def race(execution, second):
    db, admin, actor, college, task = execution
    engine, tid = db.get_bind(), task.id
    assert engine.dialect.name == "mysql"
    db.rollback()
    barrier = Barrier(2)

    def worker(kind):
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text("SET SESSION innodb_lock_wait_timeout=10"))
            session.commit()
            barrier.wait(timeout=10)
            try:
                service = InspectionService(session)
                if kind == "report":
                    service.report_exception(actor, tid, TaskCancelRequest(lock_version=0), None)
                else:
                    service.create_submission(
                        actor, tid, SubmissionCreateRequest(result="NORMAL"), None
                    )
                return "ok"
            except AppError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, kind) for kind in ("report", second)]
        results = [future.result(timeout=30) for future in futures]
    db.expire_all()
    assert sorted(results) == ["conflict", "ok"]
    return db, db.get(InspectionTask, tid)


def test_duplicate_exception_reports_commit_only_once(execution):
    db, task = race(execution, "report")
    assert task.exception_reported_at is not None
    assert task.lock_version == 1
    assert db.scalar(select(func.count()).select_from(InspectionSubmission)) == 0
    assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 0


def test_exception_and_normal_submission_cannot_both_commit(execution):
    db, task = race(execution, "submit")
    submitted = db.scalar(select(func.count()).select_from(InspectionSubmission))
    assert (task.exception_reported_at is not None) != bool(submitted)
