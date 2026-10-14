import pytest
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.identity.models import IdentityBindingToken
from app.modules.identity.service import IdentityService
from sqlalchemy import func, select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_binding_batches_reject_mixed_college_before_issuing_any_code(campus, monkeypatch):
    _, db, admin, _, a, b = campus
    *_, own, foreign = records(db, a, b)
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    service = IdentityService(db, college_id=int(a["id"]))
    with pytest.raises(NotFoundError):
        service.batch_issue_binding_tokens(actor_user_id=admin.id, student_ids=[own.id, foreign.id])
    assert db.scalar(select(func.count()).select_from(IdentityBindingToken)) == 0
    rows = service.batch_issue_binding_tokens(actor_user_id=admin.id)
    assert [str(row["student_id"]) for row in rows] == [str(own.id)]


def test_binding_legacy_management_refuses_unselected_workspace(campus, monkeypatch):
    _, db, admin, *_ = campus
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    with pytest.raises(PermissionDeniedError):
        IdentityService(db).batch_issue_binding_tokens(actor_user_id=admin.id)
