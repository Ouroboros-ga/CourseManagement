import pytest
from app.core.exceptions import ConflictError
from app.modules.inspection.group_sampling import GroupSamplingService
from app.modules.inspection.models import InspectionTask
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_group_change_records_impact_and_keeps_immutable_task(campus, monkeypatch):
    from app.modules.organization.impact_service import ConfigurationImpactService
    db, admin, a, sem, group, own, *_ = arrange(campus, monkeypatch)
    config = campus[0]
    sampler = GroupSamplingService(db, admin, int(a["id"]), int(group["id"]))
    body = {"semester_id": str(sem.id), "date_from": "2026-09-07", "date_to": "2026-09-07",
            "counts": {str(own.administrative_class_id): 1}, "draw_id": "impact"}
    generated = sampler.generate(body, sampler.preview(body)["selection_revision"])
    # Pin today for the generic impact capture, not business scheduling rules.
    monkeypatch.setattr("app.modules.organization.future_impact.business_today", lambda: __import__('datetime').date(2026, 9, 7))
    task = db.get(InspectionTask, int(generated.assignable_task_ids[0]))
    original = (task.group_config_version_id, task.activity_start_at, task.lock_version)
    current = config._resource(__import__('app.modules.volunteer.models', fromlist=['VolunteerGroup']).VolunteerGroup, int(a["id"]), int(group["id"]))
    preview = config.configuration_impact(admin, int(a["id"]), "group", int(group["id"]))
    config.update_group(
        admin,
        int(a["id"]),
        int(group["id"]),
        {
            "lock_version": current.lock_version,
            "status": "INACTIVE",
            "future_impact_revision": preview["revision"],
        },
    )
    service = ConfigurationImpactService(db, admin, int(a["id"]))
    item = service.list()["items"][0]
    assert item["task_id"] == str(task.id)
    assert item["status"] == "OPEN"
    assert original == (task.group_config_version_id, task.activity_start_at, task.lock_version)
    resolved = service.resolve(int(item["id"]), {"decision": "KEEP", "lock_version": item["lock_version"],
        "task_lock_version": item["current_task_lock_version"], "assignment_revision": item["assignment_revision"]})
    assert resolved["status"] == "KEEP"
    with pytest.raises(ConflictError):
        service.resolve(int(item["id"]), {"decision": "KEEP", "lock_version": 1,
            "task_lock_version": task.lock_version, "assignment_revision": item["assignment_revision"]})
