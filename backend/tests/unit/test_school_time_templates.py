"""School defaults are explicit immutable inputs, never a broadcast overwrite."""

from datetime import date

import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.models import Semester
from app.modules.academic.school_time import SchoolTimeService
from app.modules.academic.time_models import CollegeTimeVersion, SchoolSemesterDefault
from app.modules.academic.time_service import CollegeTimeService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def configuration(start="08:00", calendar=None):
    return {
        "effective_from": "2026-10-01",
        "periods": [{"period_no": 1, "start_time": start, "end_time": "08:45"}],
        "calendar": calendar or [],
        "grid_slot_mapping": {"1": 1},
    }


def setup(campus):
    _, db, admin, reader, a, _ = campus
    sem = Semester(
        code="2026-A",
        name="学期",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 12, 31),
        first_monday=date(2026, 9, 28),
        total_weeks=14,
    )
    db.add(sem)
    db.commit()
    return db, admin, reader, int(a["id"]), sem.id


def test_school_template_is_explicit_immutable_and_restricted(campus):
    db, admin, reader, cid, sid = setup(campus)
    service = SchoolTimeService(db, admin, sid)
    from app.modules.academic.school_time_models import (
        SchoolTimeTemplate,
        SchoolTimeTemplateVersion,
    )
    from app.modules.organization.models import College

    native = SchoolTimeTemplate(
        school_id=db.get(College, cid).school_id,
        name="通用节次",
        normalized_name="通用节次",
        latest_version=1,
    )
    db.add(native)
    db.flush()
    native_version = SchoolTimeTemplateVersion(
        template_id=native.id,
        version=1,
        name="通用节次",
        periods=configuration()["periods"],
        published_by=admin.id,
    )
    db.add(native_version)
    db.commit()
    one = service.publish(
        {"name": "秋季", "period_template_version_id": str(native_version.id), **configuration()}
    )
    assert one["period_template_version_id"] == str(native_version.id)
    two = service.publish({"name": "修订", **configuration("08:05")})
    assert one["version"] == 1 and two["version"] == 2
    assert db.scalar(select(CollegeTimeVersion.id)) is None
    assert (
        db.get(SchoolSemesterDefault, int(one["id"])).configuration["periods"][0]["start_time"]
        == "08:00:00"
    )
    with pytest.raises(PermissionDeniedError):
        SchoolTimeService(db, reader, sid).publish({"name": "非法", **configuration()})
    request = {"template_id": one["id"], "effective_from": "2026-10-01"}
    preview = service.preview_adoption(cid, request)
    service.adopt(cid, {**request, "revision": preview["revision"]})
    assert db.scalar(select(CollegeTimeVersion)).source_template_id == int(one["id"])


def test_adoption_preserves_local_exceptions_and_rejects_stale_preview(campus):
    db, admin, _, cid, sid = setup(campus)
    service = SchoolTimeService(db, admin, sid)
    first = service.publish({"name": "原版", **configuration()})
    request = {"template_id": first["id"], "effective_from": "2026-10-01"}
    service.adopt(cid, {**request, "revision": service.preview_adoption(cid, request)["revision"]})
    local = configuration("08:10", [{"date": "2026-10-20", "override_type": "STOP"}])
    time = CollegeTimeService(db, admin, cid, sid)
    time.publish(local, time.preview(local)["revision"])
    second = service.publish(
        {
            "name": "新版",
            **configuration("08:05", [{"date": "2026-10-21", "override_type": "STOP"}]),
        }
    )
    request["template_id"] = second["id"]
    preview = service.preview_adoption(cid, request)
    assert preview["configuration"]["periods"][0]["start_time"] == "08:10:00"
    assert {r["date"] for r in preview["configuration"]["calendar"]} == {"2026-10-20", "2026-10-21"}
    time.publish(local, time.preview(local)["revision"])
    with pytest.raises(ConflictError):
        service.adopt(cid, {**request, "revision": preview["revision"]})
    fresh = service.preview_adoption(cid, request)
    service.adopt(cid, {**request, "revision": fresh["revision"]})
    versions = list(db.scalars(select(CollegeTimeVersion).order_by(CollegeTimeVersion.version)))
    assert versions[-1].source_template_id == int(second["id"])
    assert versions[0].configuration["periods"][0]["start_time"] == "08:00:00"
