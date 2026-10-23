from datetime import time

import pytest
from app.core.exceptions import AppError, ConflictError
from app.modules.academic.models import PeriodDefinition
from app.modules.academic.schemas import PeriodDefinitionUpsertRequest
from app.modules.academic.service import AcademicService
from app.modules.audit.models import AuditLog
from app.modules.identity.seed import sync_registry
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def campus_setup():
    yield from campus_fixture.__wrapped__()


def setup(campus):
    _, db, actor, _, a, b = campus
    _, _, _, teaching, _, _, _ = records(db, a, b)
    sync_registry(db)
    return db, actor, teaching.semester_id, AcademicService(db)


def test_referenced_period_cannot_be_deleted_or_silently_retimed(campus):
    db, actor, sid, service = setup(campus)
    row = PeriodDefinition(
        semester_id=sid, period_no=1, start_time=time(8, 10), end_time=time(8, 55)
    )
    db.add(row)
    db.commit()
    with pytest.raises(ConflictError, match="课表"):
        service.delete_period_definition(actor, sid, row.id, None, None)
    with pytest.raises(ConflictError, match="课表"):
        service.upsert_period_definition(
            actor,
            sid,
            PeriodDefinitionUpsertRequest(
                period_no=1, start_time=time(7, 30), end_time=time(7, 50)
            ),
            None,
        )


def test_out_of_order_new_period_and_null_time_rejected(campus):
    db, actor, sid, service = setup(campus)
    db.add(
        PeriodDefinition(semester_id=sid, period_no=1, start_time=time(8, 10), end_time=time(8, 55))
    )
    db.commit()
    for start, end in [(time(7, 30), time(7, 50)), (None, None)]:
        with pytest.raises(AppError):
            service.upsert_period_definition(
                actor,
                sid,
                PeriodDefinitionUpsertRequest(period_no=13, start_time=start, end_time=end),
                None,
            )


def test_period_audit_captures_true_before_and_after(campus):
    db, actor, sid, service = setup(campus)
    row = PeriodDefinition(semester_id=sid, period_no=3, start_time=time(10), end_time=time(10, 45))
    db.add(row)
    db.commit()
    service.upsert_period_definition(
        actor,
        sid,
        PeriodDefinitionUpsertRequest(period_no=3, start_time=time(10, 5), end_time=time(10, 50)),
        None,
    )
    audit = db.scalar(
        select(AuditLog).where(AuditLog.action == "academic.period_definition.upsert")
    )
    assert audit.before_json["start_time"] == "10:00:00"
    assert audit.before_json["end_time"] == "10:45:00"
    assert audit.after_json["start_time"] == "10:05:00"


def test_initialize_only_fills_missing_and_is_atomic(campus):
    db, actor, sid, service = setup(campus)
    db.add(
        PeriodDefinition(semester_id=sid, period_no=1, start_time=time(8, 10), end_time=time(8, 55))
    )
    db.commit()
    reply = service.initialize_period_definitions(actor, sid, None)
    assert reply["created"] == 11
    assert service.initialize_period_definitions(actor, sid, None)["created"] == 0
    assert len(list(db.scalars(select(PeriodDefinition)))) == 12


def test_initialize_invalid_existing_time_does_not_partially_fill(campus):
    db, actor, sid, service = setup(campus)
    db.add(
        PeriodDefinition(
            semester_id=sid, period_no=13, start_time=time(7, 30), end_time=time(7, 50)
        )
    )
    db.commit()
    with pytest.raises(ConflictError):
        service.initialize_period_definitions(actor, sid, None)
    assert [row.period_no for row in db.scalars(select(PeriodDefinition))] == [13]
