import pytest
from app.core.exceptions import NotFoundError
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.scoped_service import ScopedInspectionService

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_inspection_reads import setup


@pytest.fixture(name="campus")
def configured():
    yield from campus_fixture.__wrapped__()


def test_selected_college_does_not_mix_other_explicit_read_grants(campus, monkeypatch):
    db, actor, a, b, own, foreign = setup(campus, monkeypatch)
    grant(campus[0], campus[2], actor, b, ["inspection.read"])
    service = ScopedInspectionService(db, actor, int(a["id"]))
    service._require(actor.id, "inspection.read")
    assert list(db.scalars(service._scope_filter(actor).with_only_columns(InspectionTask.id))) == [
        own.task_id
    ]
    with pytest.raises(NotFoundError):
        service.get_task(actor, foreign.task_id)
