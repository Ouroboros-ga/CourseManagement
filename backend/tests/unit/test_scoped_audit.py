from datetime import UTC, datetime, timedelta

import pytest
from app.core.exceptions import NotFoundError
from app.modules.audit.models import AuditLog
from app.modules.audit.service import AuditReadService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_scoped_audit_counts_details_and_unknown_history_use_immutable_scope(campus):
    config, db, admin, actor, a, b = campus
    grant(config, admin, actor, a, ["audit.read"])
    own = config.create_type(admin, int(a["id"]), {"name": "fixture A"})
    other = config.create_type(admin, int(b["id"]), {"name": "fixture B"})
    unknown = AuditLog(
        actor_user_id=admin.id,
        action="campus.type.create",
        resource_type="legacy",
        resource_id="fixture",
        after_json={"college_id": a["id"]},
    )
    db.add(unknown)
    db.commit()
    foreign = db.scalar(
        select(AuditLog).where(
            AuditLog.resource_id == other["id"], AuditLog.resource_type == "CourseType"
        )
    )
    db.get(AuditLog, foreign.id)
    service = AuditReadService(db, college_id=int(a["id"]))
    now = datetime.now(UTC)
    result = service.list_logs(
        actor.id,
        start=now - timedelta(days=1),
        end=now + timedelta(days=1),
        actor_user_id=None,
        action="campus.type.create",
        resource_type=None,
        resource_id=None,
        page=1,
        page_size=20,
    )
    assert result["total"] == 1 and result["items"][0]["resource_id"] == own["id"]
    for row in (foreign, unknown):
        with pytest.raises(NotFoundError):
            service.get(actor.id, row.id)
