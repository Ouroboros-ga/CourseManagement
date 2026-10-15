from datetime import date

import pytest
from app.core.exceptions import ConflictError

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_profile_publication_and_binding_use_actual_time_without_changing_default(campus, monkeypatch):
    from app.modules.academic.time_profiles import TimeProfileService
    from app.modules.academic.time_service import TimeResolver
    db, admin, a, sem, group, own, teaching, _ = arrange(campus, monkeypatch)
    service = TimeProfileService(db, admin, int(a["id"]), sem.id)
    draft = service.create({"name": "北校区", "configuration": {"effective_from": "2026-09-01",
        "periods": [{"period_no": 1, "start_time": "09:00", "end_time": "09:40"},
                    {"period_no": 2, "start_time": "09:50", "end_time": "10:30"}]}})
    preview = service.preview(int(draft["id"]))
    service.publish(int(draft["id"]), draft["lock_version"], preview["revision"], False)
    binding = service.binding_preview(teaching.id, int(draft["id"]))
    service.bind(teaching.id, int(draft["id"]), binding["revision"])
    resolver = TimeResolver(db)
    resolver.prefetch(int(a["id"]), sem.id)
    assert resolver.interval(int(a["id"]), sem.id, date(2026,9,7), 1, 2, teaching_class_id=teaching.id)["start_minute"] == 540
    assert resolver.interval(int(a["id"]), sem.id, date(2026,9,7), 1, 2)["start_minute"] == 420
    with pytest.raises(ConflictError):
        service.archive(int(draft["id"]), 2)

    # Published versions cannot be made unusable for an already bound course.
    row = service.list()[0]
    invalid = service.save(int(row["id"]), {"name": row["name"], "lock_version": row["lock_version"],
        "configuration": {"effective_from": "2026-09-01", "periods": [{"period_no": 1, "start_time": "11:00", "end_time": "11:40"}]}})
    preview = service.preview(int(row["id"]))
    with pytest.raises(ConflictError):
        service.publish(int(row["id"]), invalid["lock_version"], preview["revision"], True)
    assert TimeResolver(db).interval(int(a["id"]), sem.id, date(2026,9,7), 1, 2, teaching_class_id=teaching.id)["start_minute"] == 540
