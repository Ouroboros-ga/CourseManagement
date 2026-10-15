import pytest
from sqlalchemy import func, select

from app.core.exceptions import ConflictError
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_static_handoff_route_reaches_its_service(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.core.database import get_db
    from app.main import create_app
    from app.modules.academic.enrollment_service import EnrollmentService
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import CurrentUser

    for flag in ("campus_configuration_enabled", "campus_academic_scoped_enabled"):
        monkeypatch.setattr(get_settings(), flag, True)
    monkeypatch.setattr(EnrollmentService, "handoff_tasks", lambda self, actor: [])
    app = create_app()
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        1, None, "audit", "ACTIVE", ["SUPER_ADMIN"], [], pre_binding=False
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/colleges/1/academic/enrollment-handoff/tasks")
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_same_occurrence_cannot_be_generated_for_two_groups(campus, monkeypatch):
    db, actor, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    config = campus[0]
    other = config.create_group(actor, int(a["id"]), {
        "name": "another group", "owner_user_id": str(actor.id),
    })
    other = config.publish_group(actor, int(a["id"]), int(other["id"]), {
        "lock_version": other["lock_version"],
        "course_type_ids": group["configuration"]["course_type_ids"],
    })
    config.update_group(actor, int(a["id"]), int(other["id"]), {
        "lock_version": other["lock_version"], "status": "ACTIVE",
    })
    body = {"semester_id": str(sem.id), "date_from": "2026-09-07", "date_to": "2026-09-07",
            "counts": {str(own.administrative_class_id): 1}, "draw_id": "shared"}
    first = GroupSamplingService(db, actor, int(a["id"]), int(group["id"]))
    assert first.generate(body, first.preview(body)["selection_revision"]).created == 1
    assert first.generate(body, first.preview(body)["selection_revision"]).created == 0
    second = GroupSamplingService(db, actor, int(a["id"]), int(other["id"]))
    with pytest.raises(ConflictError):
        second.generate(body, second.preview(body)["selection_revision"])
    assert db.scalar(select(func.count()).select_from(InspectionTask).where(
        InspectionTask.group_id.is_not(None)
    )) == 1


def test_generic_generation_requires_and_obeys_execution_group(campus, monkeypatch):
    from app.modules.inspection.schemas import InspectionGenerateRequest
    from app.modules.inspection.scoped_service import ScopedInspectionService

    db, actor, a, sem, group, own, teaching, *_ = arrange(campus, monkeypatch)
    service = ScopedInspectionService(db, actor, int(a["id"]))
    body = InspectionGenerateRequest(semester_id=sem.id, inspection_type="COURSE",
        date_from="2026-09-07", date_to="2026-09-07", teaching_class_ids=[teaching.id])
    with pytest.raises(ConflictError):
        service.preview(actor, body)
    preview = service.preview(actor, body.model_copy(update={"execution_group_id": group["id"]}))
    assert preview.task_count == 1
